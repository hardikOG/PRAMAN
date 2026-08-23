"""`confirm_step_up`: redeeming a human's confirmation of a STEP_UP decision
— exactly-once payment capture, a new ALLOW decision + proof bundle, and the
original STEP_UP decision left untouched. Against SQLite + fakeredis +
DeterministicExecutor, no Docker required.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from apps.api.db import Base, enable_sqlite_foreign_keys
from apps.api.gateway.pipeline import PipelineThresholds, authorize, confirm_step_up, quote_to_cart
from apps.api.gateway.repository import get_decision
from apps.api.gateway.step_up import issue_step_up_token
from apps.api.ledger.bundle import verify_proof_bundle
from apps.api.ledger.crypto import generate_signing_key, public_key_b64
from apps.api.mandates.repository import save_mandate
from apps.api.mandates.service import sign_mandate
from apps.api.models.schemas import (
    Constraint,
    ConstraintType,
    DecisionOutcome,
    Mandate,
    VelocityLimits,
)
from apps.api.payments.executor import DeterministicExecutor
from fakeredis import FakeAsyncRedis
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from tests.fakes import FakeLLMClient

_THRESHOLDS = PipelineThresholds(
    replay_guard_ttl_seconds=3600,
    faithfulness_min_confidence=0.7,
    behaviour_max_req_per_sec=5.0,
    behaviour_burst_window_seconds=10.0,
    behaviour_probe_window_seconds=300.0,
    behaviour_probe_min_quotes=5,
    behaviour_loop_min_repeats=3,
    auto_strip_max_fraction=0.10,
    behaviour_step_up_threshold=0.4,
    step_up_ttl_seconds=900,
    behaviour_event_stream_maxlen=500,
)


class _QuoteItem:
    def __init__(self, sku, name, category, unit_price_paise, qty, attributes):
        self.sku = sku
        self.name = name
        self.category = category
        self.unit_price_paise = unit_price_paise
        self.qty = qty
        self.attributes = attributes


def _shoe_item(size: str = "UK9", colour: str = "Ash", price: int = 349_900) -> _QuoteItem:
    return _QuoteItem(
        "NR-A9", "Nova Runner", "footwear.running", price, 1, {"size": size, "colour": colour}
    )


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


@pytest.fixture
async def redis():
    client = FakeAsyncRedis(decode_responses=True)
    yield client
    await client.aclose()


def _mandate(key) -> Mandate:
    now = datetime.now(UTC)
    unsigned = Mandate(
        id=str(uuid.uuid4()),
        principal_id="user-1",
        agent_id="agent-1",
        public_key=public_key_b64(key),
        signature="",
        budget_total_paise=400_000,
        budget_used_paise=0,
        per_txn_cap_paise=400_000,
        merchant_allowlist=["kicks-co"],
        category_allowlist=["footwear.running"],
        velocity=VelocityLimits(max_txn_per_hour=3, max_txn_per_day=10),
        auto_strip_unrequested=True,
        intent_text="running shoes under ₹4000, size 9, not white",
        constraints=[
            Constraint(
                id="c1",
                type=ConstraintType.MAX_PRICE,
                field="price",
                operator="<=",
                value="400000",
                is_deterministic=True,
                source_span="under ₹4000",
            ),
            Constraint(
                id="c3",
                type=ConstraintType.ATTRIBUTE,
                field="size",
                operator="==",
                value="9",
                is_deterministic=False,
                source_span="size 9",
            ),
        ],
        issued_at=now,
        expires_at=now + timedelta(days=7),
    )
    return sign_mandate(unsigned, key)


async def _authorize_to_step_up(session, redis, ledger_key):
    """Produce a real STEP_UP decision (an UNDETERMINED size finding) the
    same way `authorize()` naturally would, then return its token, id, and
    the mandate/cart it belongs to."""
    principal_key = generate_signing_key()
    mandate = _mandate(principal_key)
    await save_mandate(session, mandate)
    cart = quote_to_cart(
        cart_id=str(uuid.uuid4()),
        mandate_id=mandate.id,
        merchant_id="kicks-co",
        quote_id="qte-1",
        items=[_shoe_item()],
        currency="INR",
    )
    fake_llm = FakeLLMClient({"not_a_verdict": True})  # malformed -> UNDETERMINED

    result = await authorize(
        session=session,
        redis=redis,
        mandate=mandate,
        cart=cart,
        llm_client=fake_llm,
        ledger_signing_key=ledger_key,
        payment_executor=DeterministicExecutor(),
        thresholds=_THRESHOLDS,
    )
    assert result.decision.outcome == DecisionOutcome.STEP_UP
    assert result.step_up_token is not None
    return result, mandate, cart


async def test_confirming_a_step_up_allows_and_captures_payment(session, redis) -> None:
    ledger_key = generate_signing_key()
    original_result, _mandate, _cart = await _authorize_to_step_up(session, redis, ledger_key)

    confirm = await confirm_step_up(
        session=session,
        redis=redis,
        token=original_result.step_up_token,
        ledger_signing_key=ledger_key,
        payment_executor=DeterministicExecutor(),
    )

    assert confirm.ok is True
    assert confirm.decision is not None
    assert confirm.decision.outcome == DecisionOutcome.ALLOW
    assert confirm.decision.reason_code == f"step_up_confirmed:{original_result.decision.id}"
    assert confirm.decision.razorpay_order_id is not None
    assert confirm.decision.razorpay_payment_id is not None
    assert confirm.proof_bundle is not None
    assert confirm.proof_bundle.decision_id == confirm.decision.id
    assert verify_proof_bundle(confirm.proof_bundle, ledger_key.public_key()) is True


async def test_confirming_does_not_mutate_the_original_step_up_decision(session, redis) -> None:
    ledger_key = generate_signing_key()
    original_result, _mandate, _cart = await _authorize_to_step_up(session, redis, ledger_key)
    original_id = original_result.decision.id

    await confirm_step_up(
        session=session,
        redis=redis,
        token=original_result.step_up_token,
        ledger_signing_key=ledger_key,
        payment_executor=DeterministicExecutor(),
    )

    still_original = await get_decision(session, original_id)
    assert still_original is not None
    assert still_original.outcome == "STEP_UP"
    assert still_original.razorpay_order_id is None
    assert still_original.razorpay_payment_id is None
    assert still_original.proof_bundle is None  # only the new decision gets one


async def test_token_is_single_use_even_for_confirmation(session, redis) -> None:
    ledger_key = generate_signing_key()
    original_result, _mandate, _cart = await _authorize_to_step_up(session, redis, ledger_key)

    first = await confirm_step_up(
        session=session,
        redis=redis,
        token=original_result.step_up_token,
        ledger_signing_key=ledger_key,
        payment_executor=DeterministicExecutor(),
    )
    second = await confirm_step_up(
        session=session,
        redis=redis,
        token=original_result.step_up_token,
        ledger_signing_key=ledger_key,
        payment_executor=DeterministicExecutor(),
    )

    assert first.ok is True
    assert first.decision is not None
    assert first.decision.razorpay_order_id is not None  # payment captured exactly once
    assert second.ok is False
    assert second.reason == "invalid_or_expired_token"


async def test_unknown_token_is_rejected(session, redis) -> None:
    ledger_key = generate_signing_key()
    result = await confirm_step_up(
        session=session,
        redis=redis,
        token="this-token-was-never-issued",
        ledger_signing_key=ledger_key,
        payment_executor=DeterministicExecutor(),
    )
    assert result.ok is False
    assert result.reason == "invalid_or_expired_token"
    assert result.decision is None
    assert result.proof_bundle is None


async def test_confirming_an_allow_decisions_token_is_rejected(session, redis) -> None:
    """Defense in depth: `issue_step_up_token` is only ever called on the
    STEP_UP branch in `authorize()`, so this specific token/decision-state
    mismatch can't happen through the normal flow — but `confirm_step_up`
    checks the decision's actual outcome anyway rather than trusting that a
    token's mere existence implies the state it names."""
    ledger_key = generate_signing_key()
    principal_key = generate_signing_key()
    mandate = _mandate(principal_key)
    await save_mandate(session, mandate)
    cart = quote_to_cart(
        cart_id=str(uuid.uuid4()),
        mandate_id=mandate.id,
        merchant_id="kicks-co",
        quote_id="qte-1",
        items=[_shoe_item()],
        currency="INR",
    )
    honest_llm = FakeLLMClient(
        lambda _s, u: {"verdict": "SATISFIED", "evidence": "matches", "confidence": 0.95}
    )
    allow_result = await authorize(
        session=session,
        redis=redis,
        mandate=mandate,
        cart=cart,
        llm_client=honest_llm,
        ledger_signing_key=ledger_key,
        payment_executor=DeterministicExecutor(),
        thresholds=_THRESHOLDS,
    )
    assert allow_result.decision.outcome == DecisionOutcome.ALLOW

    forged_token = await issue_step_up_token(redis, allow_result.decision.id, ttl_seconds=900)
    result = await confirm_step_up(
        session=session,
        redis=redis,
        token=forged_token,
        ledger_signing_key=ledger_key,
        payment_executor=DeterministicExecutor(),
    )
    assert result.ok is False
    assert result.reason == "decision_is_not_step_up"
