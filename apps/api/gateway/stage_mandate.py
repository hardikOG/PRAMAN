"""S1 — mandate verification. The gateway's fastest, hardest-edged stage:
signature, revocation, expiry, merchant allowlist, per-transaction cap,
budget, replay, and the mandate's own declared velocity limits. Every
failure here is a hard BLOCK (see policy.py, Phase 6) — a forged signature
or a replayed cart is never softened to a step-up.

Target: p95 under 10ms (PRAMAN_BUILD.md §9 Phase 4 gate) — nothing here
does an LLM call or anything else that could make that unrealistic; the two
Redis round-trips (replay guard, velocity check) are the only I/O.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from datetime import datetime

from redis.asyncio import Redis

from apps.api.gateway.replay_guard import check_and_mark_seen
from apps.api.mandates.service import verify_mandate_signature
from apps.api.mandates.velocity import check_velocity
from apps.api.models.schemas import Cart, Mandate


@dataclass(frozen=True)
class MandateStageResult:
    """S1's verdict: pass/fail, a stable reason code for the decision trace,
    and the wall-clock latency this check took."""

    passed: bool
    reason_code: str
    latency_ms: float


async def evaluate_mandate(
    redis: Redis,
    mandate: Mandate,
    cart: Cart,
    at: datetime,
    *,
    replay_guard_ttl_seconds: int,
) -> MandateStageResult:
    """Run every S1 check in order, stopping at the first failure.

    Order is deliberate: signature first (a forged mandate's other claims
    can't be trusted either), then status (revoked/expired), then the
    mandate's own economic terms (allowlist, cap, budget), then replay, then
    velocity — cheapest and most fundamental checks first.

    Complexity: O(1) — constant-time comparisons plus two Redis round-trips
    (replay guard, velocity check).
    """
    start = time.perf_counter()

    def _result(passed: bool, reason_code: str) -> MandateStageResult:
        return MandateStageResult(
            passed=passed, reason_code=reason_code, latency_ms=(time.perf_counter() - start) * 1000
        )

    if not verify_mandate_signature(mandate):
        return _result(False, "invalid_signature")
    if mandate.is_revoked:
        return _result(False, "revoked")
    if mandate.is_expired(at):
        return _result(False, "expired")
    if cart.merchant_id not in mandate.merchant_allowlist:
        return _result(False, "merchant_not_allowlisted")
    if cart.total_paise > mandate.per_txn_cap_paise:
        return _result(False, "per_txn_cap_exceeded")
    if mandate.budget_used_paise + cart.total_paise > mandate.budget_total_paise:
        return _result(False, "budget_exceeded")

    is_fresh = await check_and_mark_seen(redis, cart.id, ttl_seconds=replay_guard_ttl_seconds)
    if not is_fresh:
        return _result(False, "replay_detected")

    velocity = await check_velocity(redis, mandate.id, mandate.velocity, at)
    if not velocity.within_limits:
        return _result(False, "velocity_exceeded")

    return _result(True, "ok")
