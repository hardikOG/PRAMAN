"""Ledger persistence: real chain continuity across multiple saved bundles,
against SQLite (no Docker/Postgres required)."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from apps.api.db import Base, enable_sqlite_foreign_keys
from apps.api.ledger.bundle import build_proof_bundle
from apps.api.ledger.chain import GENESIS_HASH
from apps.api.ledger.crypto import generate_signing_key
from apps.api.ledger.repository import (
    get_latest_payload_hash,
    get_proof_bundle,
    get_proof_bundle_by_decision,
    save_proof_bundle,
)
from apps.api.models.tables import CartRow, DecisionRow, MandateRow
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from tests.test_ledger_chain_and_bundle import _make_payload

# `_make_payload()` always builds its Mandate/Cart with these fixed ids
# ("mnd-1"/"cart-1") — see test_ledger_chain_and_bundle.py — so a matching
# row only needs inserting once per session, regardless of how many
# payloads/decisions are built against it in one test.
_MANDATE_ID = "mnd-1"
_CART_ID = "cart-1"


async def _seed_mandate_and_cart(session) -> None:
    """`ProofBundleRow.decision_id` -> `decisions.id` -> `carts.id` ->
    `mandates.id` are real foreign keys (see apps/api/models/tables.py) —
    this repository test exercises `save_proof_bundle` in isolation from the
    gateway's own `save_cart`/`save_decision` calls, so it has to lay the
    same minimal chain down itself."""
    now = datetime.now(UTC)
    session.add(
        MandateRow(
            id=_MANDATE_ID,
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
        )
    )
    await session.flush()
    session.add(
        CartRow(
            id=_CART_ID,
            mandate_id=_MANDATE_ID,
            merchant_id="kicks-co",
            quote_id="qte-1",
            total_paise=349_900,
        )
    )
    await session.flush()


async def _seed_decision(session, decision_id: str) -> None:
    session.add(
        DecisionRow(
            id=decision_id,
            cart_id=_CART_ID,
            outcome="ALLOW",
            reason_code="all_constraints_satisfied",
            behaviour_score=0.0,
            behaviour_signals=[],
            stripped_items=[],
            stage_latencies_ms={},
        )
    )
    await session.flush()


@pytest.fixture
async def session():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    enable_sqlite_foreign_keys(engine)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    sessionmaker = async_sessionmaker(bind=engine, expire_on_commit=False)
    async with sessionmaker() as s:
        yield s
    await engine.dispose()


async def test_empty_ledger_returns_genesis_hash(session) -> None:
    assert await get_latest_payload_hash(session) == GENESIS_HASH


async def test_saved_bundle_updates_the_latest_hash(session) -> None:
    key = generate_signing_key()
    payload = _make_payload()
    await _seed_mandate_and_cart(session)
    await _seed_decision(session, payload.decision.id)
    bundle = build_proof_bundle(
        decision_id=payload.decision.id, prev_hash=GENESIS_HASH, payload=payload, signing_key=key
    )
    await save_proof_bundle(session, bundle)
    await session.commit()

    assert await get_latest_payload_hash(session) == bundle.payload_hash


async def test_three_bundles_chain_correctly_through_the_db(session) -> None:
    key = generate_signing_key()
    prev_hash = GENESIS_HASH
    saved = []
    await _seed_mandate_and_cart(session)
    for i in range(3):
        payload = _make_payload(price_paise=300_000 + i, decision_id=f"dec-{i}")
        await _seed_decision(session, payload.decision.id)
        prev_hash = await get_latest_payload_hash(session)
        bundle = build_proof_bundle(
            decision_id=payload.decision.id, prev_hash=prev_hash, payload=payload, signing_key=key
        )
        await save_proof_bundle(session, bundle)
        await session.commit()
        saved.append(bundle)

    assert saved[1].prev_hash == saved[0].payload_hash
    assert saved[2].prev_hash == saved[1].payload_hash
    assert await get_latest_payload_hash(session) == saved[2].payload_hash


async def test_get_proof_bundle_round_trips(session) -> None:
    key = generate_signing_key()
    payload = _make_payload()
    await _seed_mandate_and_cart(session)
    await _seed_decision(session, payload.decision.id)
    bundle = build_proof_bundle(
        decision_id=payload.decision.id, prev_hash=GENESIS_HASH, payload=payload, signing_key=key
    )
    await save_proof_bundle(session, bundle)
    await session.commit()

    fetched = await get_proof_bundle(session, bundle.id)
    assert fetched is not None
    assert fetched.payload_hash == bundle.payload_hash
    assert fetched.signature == bundle.signature


async def test_get_proof_bundle_by_decision(session) -> None:
    key = generate_signing_key()
    payload = _make_payload()
    await _seed_mandate_and_cart(session)
    await _seed_decision(session, payload.decision.id)
    bundle = build_proof_bundle(
        decision_id=payload.decision.id, prev_hash=GENESIS_HASH, payload=payload, signing_key=key
    )
    await save_proof_bundle(session, bundle)
    await session.commit()

    fetched = await get_proof_bundle_by_decision(session, payload.decision.id)
    assert fetched is not None
    assert fetched.id == bundle.id


async def test_unknown_bundle_id_returns_none(session) -> None:
    assert await get_proof_bundle(session, "does-not-exist") is None
