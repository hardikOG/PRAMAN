"""Proves the ORM tables (apps/api/models/tables.py) are dialect-portable:
they create and round-trip correctly on SQLite, so local dev/tests never
need a live Postgres/Docker — production still runs on Postgres via
docker-compose, using the exact same `Base.metadata`.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from apps.api.db import Base
from apps.api.models.tables import CartItemRow, CartRow, ConstraintRow, MandateRow
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine


@pytest.fixture
async def sqlite_session():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    sessionmaker = async_sessionmaker(bind=engine, expire_on_commit=False)
    async with sessionmaker() as session:
        yield session

    await engine.dispose()


async def test_mandate_with_constraints_roundtrips_on_sqlite(sqlite_session) -> None:
    now = datetime.now(UTC)
    mandate = MandateRow(
        id="mnd-1",
        principal_id="user-1",
        agent_id="agent-1",
        public_key="pk",
        signature="sig",
        budget_total_paise=400_000,
        budget_used_paise=0,
        per_txn_cap_paise=400_000,
        merchant_allowlist=["kicks-co"],
        category_allowlist=["footwear.running"],
        velocity_max_txn_per_hour=3,
        velocity_max_txn_per_day=10,
        auto_strip_unrequested=True,
        intent_text="running shoes under ₹4000, size 9, not white",
        issued_at=now,
        expires_at=now,
        constraints=[
            ConstraintRow(
                id="c1",
                type="MAX_PRICE",
                field="price",
                operator="<=",
                value="400000",
                is_deterministic=True,
                source_span="under ₹4000",
            )
        ],
    )
    sqlite_session.add(mandate)
    await sqlite_session.commit()

    fetched = await sqlite_session.get(MandateRow, "mnd-1")
    assert fetched is not None
    assert fetched.merchant_allowlist == ["kicks-co"]
    assert fetched.category_allowlist == ["footwear.running"]
    assert len(fetched.constraints) == 1
    assert fetched.constraints[0].type == "MAX_PRICE"


async def test_cart_with_items_roundtrips_on_sqlite(sqlite_session) -> None:
    now = datetime.now(UTC)
    mandate = MandateRow(
        id="mnd-2",
        principal_id="user-1",
        agent_id="agent-1",
        public_key="pk",
        signature="sig",
        budget_total_paise=400_000,
        budget_used_paise=0,
        per_txn_cap_paise=400_000,
        merchant_allowlist=["kicks-co"],
        category_allowlist=["footwear"],
        velocity_max_txn_per_hour=3,
        velocity_max_txn_per_day=10,
        auto_strip_unrequested=True,
        intent_text="shoes",
        issued_at=now,
        expires_at=now,
    )
    cart = CartRow(
        id="cart-1",
        mandate_id="mnd-2",
        merchant_id="kicks-co",
        quote_id="qte-1",
        total_paise=349_900,
        items=[
            CartItemRow(
                id="item-1",
                sku="NR-A9",
                name="Nova Runner",
                description="running shoe",
                unit_price_paise=349_900,
                qty=1,
                attributes={"size": "UK9", "colour": "Ash"},
            )
        ],
    )
    sqlite_session.add_all([mandate, cart])
    await sqlite_session.commit()

    fetched = await sqlite_session.get(CartRow, "cart-1")
    assert fetched is not None
    assert fetched.total_paise == 349_900
    assert fetched.items[0].attributes == {"size": "UK9", "colour": "Ash"}
