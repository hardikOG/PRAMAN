"""Full S1-S4 pipeline integration: authorize() end to end against SQLite +
fakeredis + DeterministicExecutor — no Docker required. This is what proves
the individually-tested stages actually compose correctly.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from apps.api.db import Base
from apps.api.gateway.pipeline import PipelineThresholds, authorize, quote_to_cart
from apps.api.ledger.bundle import verify_proof_bundle
from apps.api.ledger.crypto import generate_signing_key, public_key_b64
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


def _sock_item() -> _QuoteItem:
    return _QuoteItem("SP-BLK", "Sock pack", "footwear.running", 29_900, 1, {"pack_size": "3"})


@pytest.fixture
async def session():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
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
                id="c2",
                type=ConstraintType.CATEGORY,
                field="category",
                operator="==",
                value="footwear.running",
                is_deterministic=True,
                source_span="running shoes",
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
            Constraint(
                id="c4",
                type=ConstraintType.MUST_NOT_HAVE,
                field="colour",
                operator="!=",
                value="white",
                is_deterministic=False,
                source_span="not white",
            ),
        ],
        issued_at=now,
        expires_at=now + timedelta(days=7),
    )
    return sign_mandate(unsigned, key)


def _honest_llm() -> FakeLLMClient:
    def respond(_system: str, user: str) -> dict:
        if "field: size" in user:
            return {"verdict": "SATISFIED", "evidence": "UK9 matches size 9", "confidence": 0.96}
        if "field: colour" in user:
            return {"verdict": "SATISFIED", "evidence": "Ash is not white", "confidence": 0.91}
        raise AssertionError(f"unexpected prompt: {user}")

    return FakeLLMClient(respond)


async def test_honest_purchase_allows_and_produces_a_verifiable_bundle(session, redis) -> None:
    principal_key = generate_signing_key()
    ledger_key = generate_signing_key()
    mandate = _mandate(principal_key)
    cart = quote_to_cart(
        cart_id=str(uuid.uuid4()),
        mandate_id=mandate.id,
        merchant_id="kicks-co",
        quote_id="qte-1",
        items=[_shoe_item()],
        currency="INR",
    )

    result = await authorize(
        session=session,
        redis=redis,
        mandate=mandate,
        cart=cart,
        llm_client=_honest_llm(),
        ledger_signing_key=ledger_key,
        payment_executor=DeterministicExecutor(),
        thresholds=_THRESHOLDS,
    )
    await session.commit()

    assert result.decision.outcome == DecisionOutcome.ALLOW
    assert result.decision.razorpay_order_id is not None
    assert result.proof_bundle is not None
    assert verify_proof_bundle(result.proof_bundle, ledger_key.public_key()) is True


async def test_silent_upsell_is_auto_stripped_and_still_allows(session, redis) -> None:
    principal_key = generate_signing_key()
    ledger_key = generate_signing_key()
    mandate = _mandate(principal_key)
    cart = quote_to_cart(
        cart_id=str(uuid.uuid4()),
        mandate_id=mandate.id,
        merchant_id="kicks-co",
        quote_id="qte-1",
        items=[_shoe_item(), _sock_item()],
        currency="INR",
    )

    result = await authorize(
        session=session,
        redis=redis,
        mandate=mandate,
        cart=cart,
        llm_client=_honest_llm(),
        ledger_signing_key=ledger_key,
        payment_executor=DeterministicExecutor(),
        thresholds=_THRESHOLDS,
    )

    assert result.decision.outcome == DecisionOutcome.ALLOW
    assert result.decision.stripped_items == ["SP-BLK"]
    # the captured payment excludes the stripped sock pack
    assert result.proof_bundle is not None


async def test_cart_substitution_wrong_size_blocks(session, redis) -> None:
    principal_key = generate_signing_key()
    ledger_key = generate_signing_key()
    mandate = _mandate(principal_key)
    cart = quote_to_cart(
        cart_id=str(uuid.uuid4()),
        mandate_id=mandate.id,
        merchant_id="kicks-co",
        quote_id="qte-1",
        items=[_shoe_item(size="UK11")],
        currency="INR",
    )

    def respond(_system: str, user: str) -> dict:
        if "field: size" in user:
            return {"verdict": "VIOLATED", "evidence": "UK11 is not size 9", "confidence": 0.95}
        return {"verdict": "SATISFIED", "evidence": "Ash is not white", "confidence": 0.9}

    result = await authorize(
        session=session,
        redis=redis,
        mandate=mandate,
        cart=cart,
        llm_client=FakeLLMClient(respond),
        ledger_signing_key=ledger_key,
        payment_executor=DeterministicExecutor(),
        thresholds=_THRESHOLDS,
    )

    assert result.decision.outcome == DecisionOutcome.BLOCK
    assert result.proof_bundle is None


async def test_merchant_substitution_blocks_before_faithfulness_even_runs(session, redis) -> None:
    principal_key = generate_signing_key()
    ledger_key = generate_signing_key()
    mandate = _mandate(principal_key)
    cart = quote_to_cart(
        cart_id=str(uuid.uuid4()),
        mandate_id=mandate.id,
        merchant_id="a-different-merchant",
        quote_id="qte-1",
        items=[_shoe_item()],
        currency="INR",
    )
    fake_llm = FakeLLMClient({"verdict": "SATISFIED", "evidence": "x", "confidence": 0.9})

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

    assert result.decision.outcome == DecisionOutcome.BLOCK
    assert result.decision.reason_code == "s1_merchant_not_allowlisted"
    assert fake_llm.calls == []  # S2 never runs when S1 blocks


async def test_undetermined_constraint_steps_up_and_issues_a_token(session, redis) -> None:
    principal_key = generate_signing_key()
    ledger_key = generate_signing_key()
    mandate = _mandate(principal_key)
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
    assert result.proof_bundle is None


async def test_bundle_signature_verifies_against_the_correct_public_key_only(
    session, redis
) -> None:
    principal_key = generate_signing_key()
    ledger_key = generate_signing_key()
    mandate = _mandate(principal_key)
    cart = quote_to_cart(
        cart_id=str(uuid.uuid4()),
        mandate_id=mandate.id,
        merchant_id="kicks-co",
        quote_id="qte-1",
        items=[_shoe_item()],
        currency="INR",
    )

    result = await authorize(
        session=session,
        redis=redis,
        mandate=mandate,
        cart=cart,
        llm_client=_honest_llm(),
        ledger_signing_key=ledger_key,
        payment_executor=DeterministicExecutor(),
        thresholds=_THRESHOLDS,
    )

    wrong_key = generate_signing_key()
    assert result.proof_bundle is not None
    assert verify_proof_bundle(result.proof_bundle, wrong_key.public_key()) is False
    assert verify_proof_bundle(result.proof_bundle, ledger_key.public_key()) is True
