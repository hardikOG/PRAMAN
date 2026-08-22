"""Ledger persistence: real chain continuity across multiple saved bundles,
against SQLite (no Docker/Postgres required)."""

from __future__ import annotations

import pytest
from apps.api.db import Base
from apps.api.ledger.bundle import build_proof_bundle
from apps.api.ledger.chain import GENESIS_HASH
from apps.api.ledger.crypto import generate_signing_key
from apps.api.ledger.repository import (
    get_latest_payload_hash,
    get_proof_bundle,
    get_proof_bundle_by_decision,
    save_proof_bundle,
)
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from tests.test_ledger_chain_and_bundle import _make_payload


@pytest.fixture
async def session():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
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
    for i in range(3):
        payload = _make_payload(price_paise=300_000 + i, decision_id=f"dec-{i}")
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
