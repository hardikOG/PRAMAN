"""The console Playground's backend: a fixed set of preset scenarios (not
free-text intent), each running the real mandate-issue -> quote -> S1-S4
pipeline end to end.

Presets, not free text, because without a live `ANTHROPIC_API_KEY` this
route falls back to the same documented `OfflineDemoLLMClient` pattern as
`praman demo` — a small, honest set of canned per-field responses matching
exactly these known scenarios, not a general-purpose offline NLU stand-in.
With a real key configured, the same route runs the real
`AnthropicLLMClient` instead and any of these scenarios genuinely measures
live model behaviour.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.config import get_settings
from apps.api.db import get_db_session
from apps.api.gateway import PipelineThresholds, authorize, quote_to_cart
from apps.api.ledger.crypto import generate_signing_key, load_or_create_signing_key
from apps.api.llm_client import AnthropicLLMClient, LLMClient, OfflineDemoLLMClient
from apps.api.mandates.service import issue_mandate
from apps.api.models.schemas import VelocityLimits
from apps.api.payments import get_payment_executor
from apps.api.redis_client import get_redis
from apps.mcp_storefront.quotes import request_quote

router = APIRouter(prefix="/playground", tags=["playground"])

_INTENT = "running shoes under ₹4000, size 9, not white"

_EXTRACTION_RESPONSE = {
    "constraints": [
        {
            "type": "MAX_PRICE",
            "field": "price",
            "operator": "<=",
            "value": "400000",
            "source_span": "under ₹4000",
        },
        {
            "type": "CATEGORY",
            "field": "category",
            "operator": "==",
            "value": "footwear.running",
            "source_span": "running shoes",
        },
        {
            "type": "ATTRIBUTE",
            "field": "size",
            "operator": "==",
            "value": "9",
            "source_span": "size 9",
        },
        {
            "type": "MUST_NOT_HAVE",
            "field": "colour",
            "operator": "!=",
            "value": "white",
            "source_span": "not white",
        },
    ]
}


@dataclass(frozen=True)
class Preset:
    key: str
    label: str
    description: str
    merchant_id: str
    items: list[tuple[str, int]]


PRESETS: list[Preset] = [
    Preset("honest", "Honest purchase", "Exactly the requested shoe.", "kicks-co", [("NR-A9", 1)]),
    Preset(
        "wrong_size",
        "Cart substitution (size)",
        "Same shoe, wrong size (UK11, not UK9).",
        "kicks-co",
        [("NR-A11", 1)],
    ),
    Preset(
        "wrong_colour",
        "Cart substitution (colour)",
        "Same shoe, in white — explicitly excluded.",
        "kicks-co",
        [("NR-W9", 1)],
    ),
    Preset(
        "silent_upsell",
        "Silent upsell",
        "The right shoe, plus an unrequested sock pack — small enough to auto-strip.",
        "kicks-co",
        [("NR-A9", 1), ("SP-BLK", 1)],
    ),
    Preset(
        "large_upsell",
        "Uncertain — needs a human",
        "The right shoe, plus a bag worth 31% of the cart — too large to silently strip.",
        "kicks-co",
        [("ECHO-9", 1), ("TOTE-20", 1)],
    ),
    Preset(
        "merchant_substitution",
        "Merchant substitution",
        "The right shoe, wrong merchant.",
        "not-kicks-co",
        [("NR-A9", 1)],
    ),
    Preset(
        "prompt_injection",
        "Prompt injection",
        "A product whose description tries to instruct the verifier directly.",
        "kicks-co",
        [("INJ-GAITER", 1)],
    ),
]

_PRESETS_BY_KEY = {p.key: p for p in PRESETS}


def _offline_response(system: str, user: str) -> dict:
    if "decompose" in system.lower():
        return _EXTRACTION_RESPONSE
    if "field: size" in user:
        if "UK11" in user:
            return {"verdict": "VIOLATED", "evidence": "UK11 is not size 9", "confidence": 0.95}
        if "one-size" in user:
            return {
                "verdict": "VIOLATED",
                "evidence": "one-size does not satisfy size 9",
                "confidence": 0.9,
            }
        return {"verdict": "SATISFIED", "evidence": "UK9 matches size 9", "confidence": 0.96}
    if "field: colour" in user:
        if "White" in user:
            return {
                "verdict": "VIOLATED",
                "evidence": "item is white, explicitly excluded",
                "confidence": 0.95,
            }
        return {"verdict": "SATISFIED", "evidence": "Ash is not white", "confidence": 0.91}
    return {
        "verdict": "UNDETERMINED",
        "evidence": "no canned answer for this prompt",
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
    return OfflineDemoLLMClient(_offline_response)


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


class PlaygroundRunRequest(BaseModel):
    preset: str


class PlaygroundRunResponse(BaseModel):
    mandate_id: str
    intent_text: str
    constraints: list[dict]
    cart: dict
    decision: dict
    proof_bundle: dict | None
    step_up_token: str | None
    llm_mode: str


@router.get("/presets")
async def list_presets() -> list[dict]:
    """The scenarios the console's Playground can run."""
    return [
        {"key": p.key, "label": p.label, "description": p.description, "items": p.items}
        for p in PRESETS
    ]


@router.post("/run", response_model=PlaygroundRunResponse)
async def run_playground(
    body: PlaygroundRunRequest, session: AsyncSession = Depends(get_db_session)
) -> PlaygroundRunResponse:
    """Issue a mandate and run one preset cart through the full S1-S4
    pipeline, returning everything the console's decision trace displays.
    """
    preset = _PRESETS_BY_KEY.get(body.preset)
    if preset is None:
        raise HTTPException(status_code=404, detail=f"unknown preset: {body.preset}")

    settings = get_settings()
    llm_client = _build_llm_client()
    redis = get_redis()
    ledger_key = load_or_create_signing_key(settings.ledger_signing_key_path)
    principal_key = generate_signing_key()
    now = datetime.now(UTC)

    mandate = await issue_mandate(
        session=session,
        intent_text=_INTENT,
        principal_id="console-user",
        agent_id=f"console-agent-{uuid.uuid4().hex[:8]}",
        budget_total_paise=400_000,
        per_txn_cap_paise=400_000,
        merchant_allowlist=["kicks-co"],
        category_allowlist=["footwear.running"],
        velocity=VelocityLimits(max_txn_per_hour=3, max_txn_per_day=10),
        auto_strip_unrequested=True,
        issued_at=now,
        expires_at=now + timedelta(days=7),
        principal_signing_key=principal_key,
        llm_client=llm_client,
    )

    quote = await request_quote(
        redis, merchant_id=preset.merchant_id, skus_and_quantities=preset.items
    )
    cart = quote_to_cart(
        cart_id=quote.id,
        mandate_id=mandate.id,
        merchant_id=quote.merchant_id,
        quote_id=quote.id,
        items=quote.items,
        currency=quote.currency,
    )

    result = await authorize(
        session=session,
        redis=redis,
        mandate=mandate,
        cart=cart,
        llm_client=llm_client,
        ledger_signing_key=ledger_key,
        payment_executor=get_payment_executor(),
        thresholds=_thresholds(),
        at=now,
    )

    return PlaygroundRunResponse(
        mandate_id=mandate.id,
        intent_text=mandate.intent_text,
        constraints=[c.model_dump(mode="json") for c in mandate.constraints],
        cart=cart.model_dump(mode="json"),
        decision=result.decision.model_dump(mode="json"),
        proof_bundle=result.proof_bundle.model_dump(mode="json") if result.proof_bundle else None,
        step_up_token=result.step_up_token,
        llm_mode="live" if settings.llm_configured else "offline_demo",
    )
