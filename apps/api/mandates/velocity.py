"""Redis-backed transaction-velocity accounting for mandates.

Budget totals (`budget_used_paise`) live in Postgres, updated transactionally
when a payment captures (Phase 6) — that's slow-changing, low-contention
state that belongs in the system of record. Velocity is the opposite: a
high-frequency sliding-window rate check that S1 (Phase 4) needs to answer in
single-digit milliseconds, which is exactly what Redis counters with a TTL
are for.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from redis.asyncio import Redis

from apps.api.models.schemas import VelocityLimits

_HOUR_SECONDS = 3600
_DAY_SECONDS = 86400


def _hour_key(mandate_id: str, at: datetime) -> str:
    epoch_hour = int(at.timestamp() // _HOUR_SECONDS)
    return f"praman:velocity:{mandate_id}:hour:{epoch_hour}"


def _day_key(mandate_id: str, at: datetime) -> str:
    epoch_day = int(at.timestamp() // _DAY_SECONDS)
    return f"praman:velocity:{mandate_id}:day:{epoch_day}"


@dataclass(frozen=True)
class VelocityCheckResult:
    """The outcome of checking a mandate's transaction rate against its
    limits, plus the counts that produced the verdict (for the gateway's
    `behaviour_signals`/audit trail)."""

    within_limits: bool
    txn_count_hour: int
    txn_count_day: int


async def record_transaction(redis: Redis, mandate_id: str, at: datetime) -> None:
    """Record one transaction attempt for `mandate_id` at time `at`.

    Increments both the current hour's and current day's counters, setting a
    TTL on first write so old windows expire on their own rather than
    needing a cleanup job.

    Complexity: O(1) — two INCR + two conditional EXPIRE round-trips.
    """
    hour_key = _hour_key(mandate_id, at)
    day_key = _day_key(mandate_id, at)

    hour_count = await redis.incr(hour_key)
    if hour_count == 1:
        await redis.expire(hour_key, _HOUR_SECONDS)

    day_count = await redis.incr(day_key)
    if day_count == 1:
        await redis.expire(day_key, _DAY_SECONDS)


async def check_velocity(
    redis: Redis, mandate_id: str, limits: VelocityLimits, at: datetime
) -> VelocityCheckResult:
    """Check whether `mandate_id` is within its velocity limits as of `at`.

    This only reads the current counts — it does not record a new attempt;
    callers that intend to proceed should call `record_transaction`
    separately (checking and recording are split so a BLOCKed attempt
    doesn't itself count against future velocity).

    Complexity: O(1) — two GET round-trips.
    """
    hour_count = int(await redis.get(_hour_key(mandate_id, at)) or 0)
    day_count = int(await redis.get(_day_key(mandate_id, at)) or 0)

    within_limits = (
        hour_count < limits.max_txn_per_hour and day_count < limits.max_txn_per_day
    )
    return VelocityCheckResult(
        within_limits=within_limits, txn_count_hour=hour_count, txn_count_day=day_count
    )
