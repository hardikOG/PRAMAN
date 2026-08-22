"""The agent-facing tool functions (tools.py) — the same functions
registered on the MCP server in server.py, called directly here with no MCP
client/session needed. Redis/payment-executor/DB dependencies are swapped
for fakes via monkeypatch, exactly as they would be in the real app's cached
accessors, just redirected for the test.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from apps.api.db import Base, enable_sqlite_foreign_keys
from apps.api.ledger.crypto import generate_signing_key
from apps.api.mandates.service import issue_mandate
from apps.api.models.schemas import VelocityLimits
from apps.api.payments.executor import DeterministicExecutor
from apps.mcp_storefront import tools
from fakeredis import FakeAsyncRedis
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from tests.fakes import FakeLLMClient


def _extraction_response(_system: str, _user: str) -> dict:
    return {"constraints": []}


@pytest.fixture
async def wired(monkeypatch):
    redis = FakeAsyncRedis(decode_responses=True)
    executor = DeterministicExecutor()
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    enable_sqlite_foreign_keys(engine)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    sessionmaker = async_sessionmaker(bind=engine, expire_on_commit=False)

    monkeypatch.setattr(tools, "get_redis", lambda: redis)
    monkeypatch.setattr(tools, "get_payment_executor", lambda: executor)
    monkeypatch.setattr(tools, "get_sessionmaker", lambda: sessionmaker)
    yield
    await redis.aclose()
    await engine.dispose()


async def _issue_unconstrained_mandate(session, *, agent_id: str = "agent-1") -> str:
    """A mandate with no constraints at all (an empty-intent extraction) —
    the minimal fixture for tests that only care about the authorization
    plumbing, not S2's findings. `category_allowlist`/`merchant_allowlist`
    include everything this test module's products need."""
    key = generate_signing_key()
    now = datetime.now(UTC)
    mandate = await issue_mandate(
        session=session,
        intent_text="anything",
        principal_id="user-1",
        agent_id=agent_id,
        budget_total_paise=1_000_000,
        per_txn_cap_paise=1_000_000,
        merchant_allowlist=["kicks-co"],
        category_allowlist=["footwear.running", "footwear.accessories"],
        velocity=VelocityLimits(max_txn_per_hour=10, max_txn_per_day=50),
        auto_strip_unrequested=True,
        issued_at=now,
        expires_at=now + timedelta(days=7),
        principal_signing_key=key,
        llm_client=FakeLLMClient(_extraction_response),
    )
    await session.commit()
    return mandate.id


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


async def test_request_quote_then_submit_cart_allows_and_creates_an_order(wired) -> None:
    sessionmaker = tools.get_sessionmaker()
    async with sessionmaker() as session:
        mandate_id = await _issue_unconstrained_mandate(session)

    quote = await tools.request_quote("agent-1", items=[{"sku": "NR-A9", "qty": 1}])
    assert "error" not in quote

    result = await tools.submit_cart("agent-1", quote["id"], mandate_id)
    assert result["outcome"] == "ALLOW"
    assert result["order_id"].startswith("order_det_")
    assert result["total_paise"] == 349_900


async def test_request_quote_rejects_unknown_sku(wired) -> None:
    result = await tools.request_quote("agent-1", items=[{"sku": "NOT-REAL", "qty": 1}])
    assert "error" in result


@pytest.mark.parametrize("qty", [0, -1, -999])
async def test_request_quote_rejects_non_positive_qty_cleanly(wired, qty: int) -> None:
    """Regression: qty <= 0 used to reach `QuoteLineItem`'s `Field(ge=1)`
    validation unguarded and raise an unhandled `pydantic.ValidationError`
    instead of returning a clean `{"error": ...}`, unlike every other
    malformed-input case this function already handles."""
    result = await tools.request_quote("agent-1", items=[{"sku": "NR-A9", "qty": qty}])
    assert "error" in result


async def test_submit_cart_reports_unknown_quote(wired) -> None:
    result = await tools.submit_cart("agent-1", "does-not-exist", "mandate-does-not-matter")
    assert "error" in result


async def test_submit_cart_reports_unknown_mandate(wired) -> None:
    """Regression: `submit_cart` must run the cart through S1-S4 before any
    payment executes — a quote against a mandate id that doesn't exist must
    be rejected, not silently authorized. Before this fix, `submit_cart`
    never even looked at a mandate: it went straight from quote to
    `payment_executor.create_order()` with no gateway call in between."""
    quote = await tools.request_quote("agent-1", items=[{"sku": "NR-A9", "qty": 1}])
    result = await tools.submit_cart("agent-1", quote["id"], "does-not-exist")
    assert "error" in result
    assert "mandate" in result["error"]


async def test_submit_cart_blocks_when_merchant_not_allowlisted(wired) -> None:
    """`request_quote` in this test module always prices against "kicks-co",
    so a mandate that does *not* allowlist "kicks-co" must BLOCK via S1 —
    and, critically, must not create a payment order."""
    key = generate_signing_key()
    now = datetime.now(UTC)
    sessionmaker = tools.get_sessionmaker()
    async with sessionmaker() as session:
        mandate = await issue_mandate(
            session=session,
            intent_text="anything",
            principal_id="user-1",
            agent_id="agent-1",
            budget_total_paise=1_000_000,
            per_txn_cap_paise=1_000_000,
            merchant_allowlist=["some-other-merchant"],
            category_allowlist=["footwear.running"],
            velocity=VelocityLimits(max_txn_per_hour=10, max_txn_per_day=50),
            auto_strip_unrequested=True,
            issued_at=now,
            expires_at=now + timedelta(days=7),
            principal_signing_key=key,
            llm_client=FakeLLMClient(_extraction_response),
        )
        await session.commit()

    quote = await tools.request_quote("agent-1", items=[{"sku": "NR-A9", "qty": 1}])
    result = await tools.submit_cart("agent-1", quote["id"], mandate.id)
    assert result["outcome"] == "BLOCK"
    assert "order_id" not in result

    status_check = await tools.get_order_status("order_det_should_not_exist")
    assert status_check["status"] == "not_found"


async def test_get_order_status_end_to_end(wired) -> None:
    sessionmaker = tools.get_sessionmaker()
    async with sessionmaker() as session:
        mandate_id = await _issue_unconstrained_mandate(session, agent_id="agent-3")

    quote = await tools.request_quote("agent-3", items=[{"sku": "SP-BLK", "qty": 1}])
    result = await tools.submit_cart("agent-3", quote["id"], mandate_id)
    assert result["outcome"] == "ALLOW"

    status = await tools.get_order_status(result["order_id"])
    assert status["status"] == "captured"


async def test_quote_and_submit_both_record_behaviour_events(wired) -> None:
    from apps.api.gateway.behaviour_events import get_recent_events

    sessionmaker = tools.get_sessionmaker()
    async with sessionmaker() as session:
        mandate_id = await _issue_unconstrained_mandate(session, agent_id="agent-2")

    quote = await tools.request_quote("agent-2", items=[{"sku": "NR-A9", "qty": 1}])
    await tools.submit_cart("agent-2", quote["id"], mandate_id)

    redis = tools.get_redis()
    events = await get_recent_events(
        redis, "agent-2", since=datetime.now(UTC) - timedelta(minutes=1)
    )
    event_types = {e.event_type for e in events}
    assert "quote_requested" in event_types
    assert "cart_submitted" in event_types
