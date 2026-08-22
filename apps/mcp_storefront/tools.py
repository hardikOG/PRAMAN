"""The five MCP tools a buyer agent calls: `search_products`, `get_product`,
`request_quote`, `submit_cart`, `get_order_status`.

Each function's signature here *is* the tool schema an agent sees (MCP
derives it from type hints/docstring) — so these take only agent-facing
arguments and reach for Redis/the payment executor via the app's existing
cached accessors, the same pattern `routes/health.py` already uses, rather
than exposing internal dependencies as tool parameters.

`submit_cart` intentionally goes straight to the payment executor for now —
Phase 3's gate is proving search → quote → cart → a real Razorpay order
works at all. Phase 6 inserts the PRAMAN gateway's `/authorize` call between
quote confirmation and order creation; this function is exactly where that
call will be added, noted so the later change doesn't surprise anyone
re-reading this file.
"""

from __future__ import annotations

from apps.api.payments import get_payment_executor
from apps.api.redis_client import get_redis
from apps.mcp_storefront.catalog import get_product as _get_product
from apps.mcp_storefront.catalog import search_catalog
from apps.mcp_storefront.quotes import UnknownSkuError, get_quote
from apps.mcp_storefront.quotes import request_quote as _request_quote


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


async def request_quote(items: list[dict]) -> dict:
    """Price a set of `{"sku": ..., "qty": ...}` items, returning a quote id
    valid for 15 minutes.
    """
    try:
        pairs = [(item["sku"], int(item.get("qty", 1))) for item in items]
    except (KeyError, TypeError, ValueError):
        return {"error": "each item must be {'sku': str, 'qty': int}"}

    try:
        quote = await _request_quote(get_redis(), merchant_id="kicks-co", skus_and_quantities=pairs)
    except UnknownSkuError as exc:
        return {"error": str(exc)}
    return quote.model_dump(mode="json")


async def submit_cart(quote_id: str) -> dict:
    """Submit a previously requested quote for payment, returning the
    Razorpay (or deterministic) order id.
    """
    quote = await get_quote(get_redis(), quote_id)
    if quote is None:
        return {"error": f"quote not found or expired: {quote_id}"}

    executor = get_payment_executor()
    order = await executor.create_order(
        amount_paise=quote.total_paise, currency=quote.currency, receipt=quote.id
    )
    return {"order_id": order.order_id, "status": order.status, "total_paise": quote.total_paise}


async def get_order_status(order_id: str) -> dict:
    """Check an order's current status."""
    executor = get_payment_executor()
    status = await executor.get_order_status(order_id=order_id)
    return {"order_id": order_id, "status": status}
