"""Quote pricing and Redis-backed storage, against fakeredis."""

from __future__ import annotations

import pytest
from apps.mcp_storefront.quotes import UnknownSkuError, get_quote, request_quote
from fakeredis import FakeAsyncRedis


@pytest.fixture
async def redis():
    client = FakeAsyncRedis(decode_responses=True)
    yield client
    await client.aclose()


async def test_request_quote_prices_items_correctly(redis) -> None:
    quote = await request_quote(
        redis, merchant_id="kicks-co", skus_and_quantities=[("NR-A9", 1), ("SP-BLK", 2)]
    )
    assert quote.total_paise == 349_900 + 2 * 29_900
    assert {item.sku for item in quote.items} == {"NR-A9", "SP-BLK"}


async def test_request_quote_rejects_unknown_sku(redis) -> None:
    with pytest.raises(UnknownSkuError):
        await request_quote(redis, merchant_id="kicks-co", skus_and_quantities=[("NOT-REAL", 1)])


async def test_get_quote_returns_a_previously_stored_quote(redis) -> None:
    quote = await request_quote(redis, merchant_id="kicks-co", skus_and_quantities=[("NR-A9", 1)])
    fetched = await get_quote(redis, quote.id)
    assert fetched is not None
    assert fetched.id == quote.id
    assert fetched.total_paise == quote.total_paise


async def test_get_quote_returns_none_for_unknown_id(redis) -> None:
    assert await get_quote(redis, "does-not-exist") is None
