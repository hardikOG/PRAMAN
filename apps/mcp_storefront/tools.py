"""The five MCP tools a buyer agent calls: `search_products`, `get_product`,
`request_quote`, `submit_cart`, `get_order_status`.

Each function's signature here *is* the tool schema an agent sees (MCP
derives it from type hints/docstring) — so these take only agent-facing
arguments and reach for Redis/the payment executor via the app's existing
cached accessors, the same pattern `routes/health.py` already uses, rather
than exposing internal dependencies as tool parameters.

`submit_cart` runs the quote through the full PRAMAN gateway (`authorize()`)
before any money moves — this is the one interface a real buyer agent
actually calls, so it is exactly where a mandate check that gets skipped
would matter most. (A prior version of this file went straight from quote
to `payment_executor.create_order()` with no gateway call in between at
all — a real bug, not just a stale comment: MCP traffic was completely
unauthorized. Fixed by routing through `authorize()` here, the same call
`routes/playground.py` and `praman demo` already make.)

`request_quote` and `submit_cart` take an `agent_id` parameter: S3's
price-probe and repeated-cart-loop signals need to attribute quote/purchase
activity to a calling agent, and there is no other channel this MCP server
has for caller identity yet. `submit_cart` additionally takes a
`mandate_id` — the human-issued authorization this purchase is claimed
against — since there is no way to run S1 mandate verification without one.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from apps.api.config import get_settings
from apps.api.db import get_sessionmaker
from apps.api.gateway import PipelineThresholds, authorize, quote_to_cart
from apps.api.gateway.behaviour_events import cart_signature, record_agent_event
from apps.api.ledger.crypto import load_or_create_signing_key
from apps.api.llm_client import AnthropicLLMClient, LLMClient, OfflineDemoLLMClient
from apps.api.mandates.service import fetch_mandate
from apps.api.models.schemas import DecisionOutcome
from apps.api.payments import get_payment_executor
from apps.api.redis_client import get_redis
from apps.mcp_storefront.catalog import get_product as _get_product
from apps.mcp_storefront.catalog import search_catalog
from apps.mcp_storefront.quotes import UnknownSkuError, get_quote
from apps.mcp_storefront.quotes import request_quote as _request_quote

_NO_LLM_CONFIGURED_RESPONSE = {
    "verdict": "UNDETERMINED",
    "evidence": "no ANTHROPIC_API_KEY configured for this MCP session",
    "confidence": 0.0,
}


def _build_llm_client() -> LLMClient:
    settings = get_settings()
    if settings.llm_configured:
        return AnthropicLLMClient(
            api_key=settings.anthropic_api_key,
            model=settings.llm_model,
            timeout_seconds=settings.llm_timeout_seconds,
            max_retries=settings.llm_max_retries,
            cache_dir=settings.llm_cache_dir,
        )
    # Unlike `routes/playground.py`'s offline client, this one has no fixed
    # set of demo scenarios to pattern-match against — real MCP traffic can
    # name any product and any constraint. A fixed UNDETERMINED response
    # keeps every LLM-adjudicated constraint honestly "can't tell" (routing
    # to STEP_UP) rather than fabricating a SATISFIED that happens to fit a
    # different scenario's canned answer.
    return OfflineDemoLLMClient(_NO_LLM_CONFIGURED_RESPONSE)


def _thresholds() -> PipelineThresholds:
    s = get_settings()
    return PipelineThresholds(
        replay_guard_ttl_seconds=s.replay_guard_ttl_seconds,
        faithfulness_min_confidence=s.faithfulness_min_confidence,
        behaviour_max_req_per_sec=s.behaviour_max_req_per_sec,
        behaviour_burst_window_seconds=s.behaviour_burst_window_seconds,
        behaviour_probe_window_seconds=s.behaviour_probe_window_seconds,
        behaviour_probe_min_quotes=s.behaviour_probe_min_quotes,
        behaviour_loop_min_repeats=s.behaviour_loop_min_repeats,
        auto_strip_max_fraction=s.auto_strip_max_fraction,
        behaviour_step_up_threshold=s.behaviour_step_up_threshold,
        step_up_ttl_seconds=s.step_up_ttl_seconds,
        behaviour_event_stream_maxlen=s.behaviour_event_stream_maxlen,
    )


async def search_products(
    query: str = "", category: str = "", max_price_paise: int | None = None
) -> list[dict]:
    """Search the catalog by name/description text, category, and/or a price
    ceiling. Returns name/price/attributes but not the full description —
    call `get_product` for that.
    """
    results = search_catalog(
        query=query or None, category=category or None, max_price_paise=max_price_paise
    )
    return [
        {
            "sku": p.sku,
            "name": p.name,
            "category": p.category,
            "price_paise": p.price_paise,
            "attributes": p.attributes,
        }
        for p in results
        if p.in_stock
    ]


async def get_product(sku: str) -> dict:
    """Fetch full details (including the description) for one SKU."""
    product = _get_product(sku)
    if product is None:
        return {"error": f"unknown SKU: {sku}"}
    return product.model_dump()


async def request_quote(agent_id: str, items: list[dict]) -> dict:
    """Price a set of `{"sku": ..., "qty": ...}` items, returning a quote id
    valid for 15 minutes.
    """
    try:
        pairs = [(item["sku"], int(item.get("qty", 1))) for item in items]
    except (KeyError, TypeError, ValueError):
        return {"error": "each item must be {'sku': str, 'qty': int}"}
    if any(qty < 1 for _sku, qty in pairs):
        # Without this check, a qty <= 0 reaches `QuoteLineItem`'s own
        # `Field(ge=1)` validation deeper in `_request_quote` and raises an
        # unhandled `pydantic.ValidationError` instead of a clean error
        # response — every other malformed-input case here is caught, this
        # one wasn't.
        return {"error": "qty must be at least 1"}

    redis = get_redis()
    settings = get_settings()
    await record_agent_event(
        redis,
        agent_id,
        "quote_requested",
        datetime.now(UTC),
        cart_signature=cart_signature(pairs),
        maxlen=settings.behaviour_event_stream_maxlen,
    )

    try:
        quote = await _request_quote(redis, merchant_id="kicks-co", skus_and_quantities=pairs)
    except UnknownSkuError as exc:
        return {"error": str(exc)}
    return quote.model_dump(mode="json")


async def submit_cart(agent_id: str, quote_id: str, mandate_id: str) -> dict:
    """Submit a previously requested quote for payment, against `mandate_id`.

    Runs the full S1-S4 PRAMAN gateway (`authorize()`) before any money
    moves. Returns the outcome plus, depending on it: the captured order
    (ALLOW), a step-up token the human must confirm (STEP_UP), or why the
    cart was rejected (BLOCK) — never an order id without a matching ALLOW.
    """
    redis = get_redis()
    quote = await get_quote(redis, quote_id)
    if quote is None:
        return {"error": f"quote not found or expired: {quote_id}"}

    await record_agent_event(
        redis,
        agent_id,
        "cart_submitted",
        datetime.now(UTC),
        cart_signature=cart_signature([(item.sku, item.qty) for item in quote.items]),
        maxlen=get_settings().behaviour_event_stream_maxlen,
    )

    sessionmaker = get_sessionmaker()
    async with sessionmaker() as session:
        mandate = await fetch_mandate(session, mandate_id)
        if mandate is None:
            return {"error": f"unknown mandate_id: {mandate_id}"}

        cart = quote_to_cart(
            cart_id=str(uuid.uuid4()),
            mandate_id=mandate.id,
            merchant_id=quote.merchant_id,
            quote_id=quote.id,
            items=quote.items,
            currency=quote.currency,
        )

        settings = get_settings()
        result = await authorize(
            session=session,
            redis=redis,
            mandate=mandate,
            cart=cart,
            llm_client=_build_llm_client(),
            ledger_signing_key=load_or_create_signing_key(settings.ledger_signing_key_path),
            payment_executor=get_payment_executor(),
            thresholds=_thresholds(),
        )
        await session.commit()

    decision = result.decision
    if decision.outcome == DecisionOutcome.ALLOW:
        return {
            "outcome": decision.outcome.value,
            "order_id": decision.razorpay_order_id,
            "payment_id": decision.razorpay_payment_id,
            "stripped_items": decision.stripped_items,
            "total_paise": quote.total_paise,
        }
    if decision.outcome == DecisionOutcome.STEP_UP:
        return {
            "outcome": decision.outcome.value,
            "reason": decision.reason_code,
            "step_up_token": result.step_up_token,
        }
    return {"outcome": decision.outcome.value, "reason": decision.reason_code}


async def get_order_status(order_id: str) -> dict:
    """Check an order's current status."""
    executor = get_payment_executor()
    status = await executor.get_order_status(order_id=order_id)
    return {"order_id": order_id, "status": status}
