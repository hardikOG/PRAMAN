"""Short-lived quotes: an agent requests a price lock on a set of SKUs
before submitting a cart. Stored in Redis with a TTL — quotes are cheap,
ephemeral, and never need to survive a restart (see PRAMAN_BUILD.md §4:
Redis owns "quote cache" alongside behaviour streams and step-up tokens).
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

from pydantic import BaseModel, ConfigDict, Field
from redis.asyncio import Redis

from apps.mcp_storefront.catalog import get_product

QUOTE_TTL_SECONDS = 900


class QuoteLineItem(BaseModel):
    """One requested SKU/quantity pair, as priced into a `Quote`."""

    model_config = ConfigDict(frozen=True)

    sku: str
    name: str
    unit_price_paise: int = Field(ge=0)
    qty: int = Field(ge=1)
    attributes: dict[str, str] = Field(default_factory=dict)


class Quote(BaseModel):
    """A price lock: the exact items and total an agent can submit as a cart
    before `expires_at`."""

    model_config = ConfigDict(frozen=True)

    id: str
    merchant_id: str
    items: list[QuoteLineItem]
    total_paise: int = Field(ge=0)
    currency: str = "INR"
    created_at: datetime
    expires_at: datetime


class UnknownSkuError(ValueError):
    """Raised when a requested SKU isn't in the catalog."""


def _quote_key(quote_id: str) -> str:
    return f"praman:quote:{quote_id}"


async def request_quote(
    redis: Redis, *, merchant_id: str, skus_and_quantities: list[tuple[str, int]]
) -> Quote:
    """Price a set of SKUs and store the resulting quote in Redis.

    Inputs: `skus_and_quantities` — `(sku, qty)` pairs.
    Outputs: a `Quote` with `id` set; also written to Redis under that id
        with a `QUOTE_TTL_SECONDS` expiry.
    Failure cases: raises `UnknownSkuError` if any SKU isn't in the catalog
        — a quote is never partially priced.
    Complexity: O(k) catalog lookups (k = number of requested SKUs) + one
        Redis SET.
    """
    items: list[QuoteLineItem] = []
    for sku, qty in skus_and_quantities:
        product = get_product(sku)
        if product is None:
            raise UnknownSkuError(f"unknown SKU: {sku}")
        items.append(
            QuoteLineItem(
                sku=product.sku,
                name=product.name,
                unit_price_paise=product.price_paise,
                qty=qty,
                attributes=product.attributes,
            )
        )

    now = datetime.now(UTC)
    quote = Quote(
        id=str(uuid.uuid4()),
        merchant_id=merchant_id,
        items=items,
        total_paise=sum(item.unit_price_paise * item.qty for item in items),
        created_at=now,
        expires_at=now + timedelta(seconds=QUOTE_TTL_SECONDS),
    )
    await redis.set(_quote_key(quote.id), quote.model_dump_json(), ex=QUOTE_TTL_SECONDS)
    return quote


async def get_quote(redis: Redis, quote_id: str) -> Quote | None:
    """Fetch a previously issued quote, or `None` if it never existed or has
    expired (Redis's TTL has already evicted it)."""
    raw = await redis.get(_quote_key(quote_id))
    return Quote.model_validate_json(raw) if raw is not None else None
