"""Mandate issuance, signature verification, expiry, and revocation —
against an in-memory SQLite DB (no Docker/Postgres required).
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from apps.api.db import Base
from apps.api.ledger.crypto import generate_signing_key
from apps.api.mandates.service import (
    fetch_mandate,
    issue_mandate,
    revoke,
    verify_mandate,
    verify_mandate_signature,
)
from apps.api.models.schemas import VelocityLimits
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from tests.fakes import FakeLLMClient
from tests.test_constraint_extraction import _GATE_INTENT, _GATE_LLM_RESPONSE


@pytest.fixture
async def session():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    sessionmaker = async_sessionmaker(bind=engine, expire_on_commit=False)
    async with sessionmaker() as s:
        yield s
    await engine.dispose()


async def _issue(session, *, expires_in: timedelta = timedelta(days=7)):
    now = datetime.now(UTC)
    key = generate_signing_key()
    mandate = await issue_mandate(
        session=session,
        intent_text=_GATE_INTENT,
        principal_id="user-1",
        agent_id="agent-1",
        budget_total_paise=400_000,
        per_txn_cap_paise=400_000,
        merchant_allowlist=["kicks-co"],
        category_allowlist=["footwear.running"],
        velocity=VelocityLimits(max_txn_per_hour=3, max_txn_per_day=10),
        auto_strip_unrequested=True,
        issued_at=now,
        expires_at=now + expires_in,
        principal_signing_key=key,
        llm_client=FakeLLMClient(_GATE_LLM_RESPONSE),
    )
    return mandate, key


async def test_issue_mandate_persists_and_signs(session) -> None:
    mandate, _key = await _issue(session)

    assert len(mandate.constraints) == 4
    assert mandate.signature != ""
    assert verify_mandate_signature(mandate) is True

    fetched = await fetch_mandate(session, mandate.id)
    assert fetched is not None
    assert fetched.id == mandate.id
    assert fetched.signature == mandate.signature
    assert len(fetched.constraints) == 4


async def test_verify_mandate_ok_for_a_fresh_valid_mandate(session) -> None:
    mandate, _key = await _issue(session)
    result = verify_mandate(mandate, datetime.now(UTC))
    assert result.valid is True
    assert result.reason == "ok"


async def test_verify_mandate_fails_when_expired(session) -> None:
    mandate, _key = await _issue(session, expires_in=timedelta(seconds=-1))
    result = verify_mandate(mandate, datetime.now(UTC))
    assert result.valid is False
    assert result.reason == "expired"


async def test_verify_mandate_fails_when_tampered(session) -> None:
    mandate, _key = await _issue(session)
    tampered = mandate.model_copy(update={"budget_total_paise": 999_999_999})
    result = verify_mandate(tampered, datetime.now(UTC))
    assert result.valid is False
    assert result.reason == "invalid_signature"


async def test_revoked_mandate_fails_verification(session) -> None:
    mandate, _key = await _issue(session)

    revoked = await revoke(session, mandate.id, datetime.now(UTC))
    assert revoked is not None
    assert revoked.is_revoked is True

    result = verify_mandate(revoked, datetime.now(UTC))
    assert result.valid is False
    assert result.reason == "revoked"


async def test_revoking_does_not_itself_invalidate_the_signature(session) -> None:
    """Regression: `revoked_at` must be excluded from the signed payload —
    otherwise revoking a mandate reports `invalid_signature` instead of
    `revoked`, masking the real reason."""
    mandate, _key = await _issue(session)
    revoked = await revoke(session, mandate.id, datetime.now(UTC))
    assert verify_mandate_signature(revoked) is True


async def test_revoking_a_nonexistent_mandate_returns_none(session) -> None:
    result = await revoke(session, "does-not-exist", datetime.now(UTC))
    assert result is None


async def test_revoke_is_idempotent(session) -> None:
    mandate, _key = await _issue(session)
    at_1 = datetime.now(UTC)
    at_2 = at_1 + timedelta(minutes=5)

    first = await revoke(session, mandate.id, at_1)
    second = await revoke(session, mandate.id, at_2)

    assert first.revoked_at == second.revoked_at
