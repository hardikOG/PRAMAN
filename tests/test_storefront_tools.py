"""The agent-facing tool functions (tools.py) — the same functions
registered on the MCP server in server.py, called directly here with no MCP
client/session needed. Redis/payment-executor dependencies are swapped for
fakes via monkeypatch, exactly as they would be in the real app's cached
accessors, just redirected for the test.
"""

from __future__ import annotations

import pytest
from apps.api.payments.executor import DeterministicExecutor
from apps.mcp_storefront import tools
from fakeredis import FakeAsyncRedis


@pytest.fixture
async def wired(monkeypatch):
    redis = FakeAsyncRedis(decode_responses=True)
    executor = DeterministicExecutor()
    monkeypatch.setattr(tools, "get_redis", lambda: redis)
    monkeypatch.setattr(tools, "get_payment_executor", lambda: executor)
    yield
    await redis.aclose()


async def test_search_products_finds_the_gate_scenario_item(wired) -> None:
    results = await tools.search_products(category="footwear.running", max_price_paise=400_000)
    skus = {r["sku"] for r in results}
    assert "NR-A9" in skus
    assert all("description" not in r for r in results)


async def test_get_product_returns_full_details(wired) -> None:
    result = await tools.get_product("NR-A9")
    assert result["sku"] == "NR-A9"
    assert "description" in result


async def test_get_product_reports_unknown_sku(wired) -> None:
    result = await tools.get_product("NOT-REAL")
    assert "error" in result


async def test_request_quote_then_submit_cart_creates_an_order(wired) -> None:
    quote = await tools.request_quote("agent-1", items=[{"sku": "NR-A9", "qty": 1}])
    assert "error" not in quote
    assert quote["total_paise"] == 349_900

    order = await tools.submit_cart("agent-1", quote["id"])
    assert "error" not in order
    assert order["order_id"].startswith("order_det_")
    assert order["total_paise"] == 349_900


async def test_submit_cart_reports_unknown_quote(wired) -> None:
    result = await tools.submit_cart("agent-1", "does-not-exist")
    assert "error" in result


async def test_request_quote_rejects_unknown_sku(wired) -> None:
    result = await tools.request_quote("agent-1", items=[{"sku": "NOT-REAL", "qty": 1}])
    assert "error" in result


async def test_get_order_status_end_to_end(wired) -> None:
    quote = await tools.request_quote("agent-1", items=[{"sku": "SP-BLK", "qty": 1}])
    order = await tools.submit_cart("agent-1", quote["id"])

    status = await tools.get_order_status(order["order_id"])
    assert status["status"] == "created"


async def test_quote_and_submit_both_record_behaviour_events(wired) -> None:
    from datetime import UTC, datetime, timedelta

    from apps.api.gateway.behaviour_events import get_recent_events

    quote = await tools.request_quote("agent-2", items=[{"sku": "NR-A9", "qty": 1}])
    await tools.submit_cart("agent-2", quote["id"])

    redis = tools.get_redis()
    events = await get_recent_events(
        redis, "agent-2", since=datetime.now(UTC) - timedelta(minutes=1)
    )
    event_types = {e.event_type for e in events}
    assert "quote_requested" in event_types
    assert "cart_submitted" in event_types
