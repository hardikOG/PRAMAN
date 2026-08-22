"""S1 — mandate verification. Phase 4 gate: replay, merchant substitution,
and velocity drain are all blocked with correct reason codes; p95 latency
under 10ms.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from apps.api.gateway.stage_mandate import evaluate_mandate
from apps.api.ledger.crypto import generate_signing_key, public_key_b64
from apps.api.mandates.service import sign_mandate
from apps.api.mandates.velocity import record_transaction
from apps.api.models.schemas import Cart, CartItem, Mandate, VelocityLimits
from fakeredis import FakeAsyncRedis

_REPLAY_TTL = 3600


@pytest.fixture
async def redis():
    client = FakeAsyncRedis(decode_responses=True)
    yield client
    await client.aclose()


def _mandate(
    *,
    key=None,
    budget_total_paise: int = 400_000,
    budget_used_paise: int = 0,
    per_txn_cap_paise: int = 400_000,
    merchant_allowlist: list[str] | None = None,
    velocity: VelocityLimits | None = None,
    expires_in: timedelta = timedelta(days=7),
    revoked_at: datetime | None = None,
) -> tuple[Mandate, object]:
    key = key or generate_signing_key()
    now = datetime.now(UTC)
    unsigned = Mandate(
        id=str(uuid.uuid4()),
        principal_id="user-1",
        agent_id="agent-1",
        public_key=public_key_b64(key),
        signature="",
        budget_total_paise=budget_total_paise,
        budget_used_paise=budget_used_paise,
        per_txn_cap_paise=per_txn_cap_paise,
        merchant_allowlist=merchant_allowlist or ["kicks-co"],
        category_allowlist=["footwear.running"],
        velocity=velocity or VelocityLimits(max_txn_per_hour=3, max_txn_per_day=10),
        auto_strip_unrequested=True,
        intent_text="running shoes under ₹4000",
        constraints=[],
        issued_at=now,
        expires_at=now + expires_in,
        revoked_at=revoked_at,
    )
    mandate = sign_mandate(unsigned, key)
    return mandate, key


def _cart(mandate_id: str, *, merchant_id: str = "kicks-co", total_paise: int = 349_900) -> Cart:
    return Cart(
        id=str(uuid.uuid4()),
        mandate_id=mandate_id,
        merchant_id=merchant_id,
        quote_id="qte-1",
        items=[
            CartItem(
                sku="NR-A9", name="Nova Runner", description="", unit_price_paise=total_paise, qty=1
            )
        ],
        total_paise=total_paise,
    )


async def test_valid_mandate_and_cart_passes(redis) -> None:
    mandate, _key = _mandate()
    cart = _cart(mandate.id)
    result = await evaluate_mandate(
        redis, mandate, cart, datetime.now(UTC), replay_guard_ttl_seconds=_REPLAY_TTL
    )
    assert result.passed is True
    assert result.reason_code == "ok"


async def test_tampered_mandate_fails_with_invalid_signature(redis) -> None:
    mandate, _key = _mandate()
    tampered = mandate.model_copy(update={"budget_total_paise": 999_999_999})
    cart = _cart(tampered.id)
    result = await evaluate_mandate(
        redis, tampered, cart, datetime.now(UTC), replay_guard_ttl_seconds=_REPLAY_TTL
    )
    assert result.passed is False
    assert result.reason_code == "invalid_signature"


async def test_revoked_mandate_is_blocked(redis) -> None:
    mandate, _key = _mandate(revoked_at=datetime.now(UTC))
    cart = _cart(mandate.id)
    result = await evaluate_mandate(
        redis, mandate, cart, datetime.now(UTC), replay_guard_ttl_seconds=_REPLAY_TTL
    )
    assert result.passed is False
    assert result.reason_code == "revoked"


async def test_expired_mandate_is_blocked(redis) -> None:
    mandate, _key = _mandate(expires_in=timedelta(seconds=-1))
    cart = _cart(mandate.id)
    result = await evaluate_mandate(
        redis, mandate, cart, datetime.now(UTC), replay_guard_ttl_seconds=_REPLAY_TTL
    )
    assert result.passed is False
    assert result.reason_code == "expired"


async def test_merchant_substitution_is_blocked(redis) -> None:
    """Red team class 6: routing the order to a merchant outside the
    mandate's allowlist."""
    mandate, _key = _mandate(merchant_allowlist=["kicks-co"])
    cart = _cart(mandate.id, merchant_id="a-different-merchant")
    result = await evaluate_mandate(
        redis, mandate, cart, datetime.now(UTC), replay_guard_ttl_seconds=_REPLAY_TTL
    )
    assert result.passed is False
    assert result.reason_code == "merchant_not_allowlisted"


async def test_per_transaction_cap_is_enforced(redis) -> None:
    mandate, _key = _mandate(per_txn_cap_paise=100_000)
    cart = _cart(mandate.id, total_paise=349_900)
    result = await evaluate_mandate(
        redis, mandate, cart, datetime.now(UTC), replay_guard_ttl_seconds=_REPLAY_TTL
    )
    assert result.passed is False
    assert result.reason_code == "per_txn_cap_exceeded"


async def test_budget_exceeded_is_enforced(redis) -> None:
    mandate, _key = _mandate(budget_total_paise=400_000, budget_used_paise=100_000)
    cart = _cart(mandate.id, total_paise=349_900)
    result = await evaluate_mandate(
        redis, mandate, cart, datetime.now(UTC), replay_guard_ttl_seconds=_REPLAY_TTL
    )
    assert result.passed is False
    assert result.reason_code == "budget_exceeded"


async def test_mandate_replay_is_blocked(redis) -> None:
    """Red team class 5: resubmitting a previously used mandate assertion
    (the same cart id) a second time."""
    mandate, _key = _mandate()
    cart = _cart(mandate.id)
    now = datetime.now(UTC)

    first = await evaluate_mandate(redis, mandate, cart, now, replay_guard_ttl_seconds=_REPLAY_TTL)
    assert first.passed is True

    second = await evaluate_mandate(redis, mandate, cart, now, replay_guard_ttl_seconds=_REPLAY_TTL)
    assert second.passed is False
    assert second.reason_code == "replay_detected"


async def test_velocity_drain_via_mandate_declared_limits_is_blocked(redis) -> None:
    """Many small in-policy purchases exceeding the mandate's own declared
    hourly transaction cap."""
    mandate, _key = _mandate(velocity=VelocityLimits(max_txn_per_hour=2, max_txn_per_day=10))
    now = datetime.now(UTC)

    await record_transaction(redis, mandate.id, now)
    await record_transaction(redis, mandate.id, now)

    cart = _cart(mandate.id)
    result = await evaluate_mandate(redis, mandate, cart, now, replay_guard_ttl_seconds=_REPLAY_TTL)
    assert result.passed is False
    assert result.reason_code == "velocity_exceeded"


async def test_s1_p95_latency_is_under_10ms(redis) -> None:
    """Phase 4 gate: S1 p95 under 10ms."""
    latencies_ms: list[float] = []
    for _ in range(200):
        mandate, _key = _mandate()
        cart = _cart(mandate.id)
        result = await evaluate_mandate(
            redis, mandate, cart, datetime.now(UTC), replay_guard_ttl_seconds=_REPLAY_TTL
        )
        assert result.passed is True
        latencies_ms.append(result.latency_ms)

    latencies_ms.sort()
    p95 = latencies_ms[int(len(latencies_ms) * 0.95)]
    assert p95 < 10.0, f"S1 p95 latency was {p95:.2f}ms, expected < 10ms"
