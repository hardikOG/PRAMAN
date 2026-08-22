"""Velocity accounting against `fakeredis` — no live Redis/Docker required."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from apps.api.mandates.velocity import check_velocity, record_transaction
from apps.api.models.schemas import VelocityLimits
from fakeredis import FakeAsyncRedis


@pytest.fixture
async def redis():
    client = FakeAsyncRedis(decode_responses=True)
    yield client
    await client.aclose()


async def test_within_limits_when_no_transactions_recorded(redis) -> None:
    limits = VelocityLimits(max_txn_per_hour=3, max_txn_per_day=10)
    result = await check_velocity(redis, "mnd-1", limits, datetime.now(UTC))
    assert result.within_limits is True
    assert result.txn_count_hour == 0
    assert result.txn_count_day == 0


async def test_recording_transactions_increments_counts(redis) -> None:
    now = datetime.now(UTC)
    limits = VelocityLimits(max_txn_per_hour=3, max_txn_per_day=10)

    await record_transaction(redis, "mnd-1", now)
    await record_transaction(redis, "mnd-1", now)

    result = await check_velocity(redis, "mnd-1", limits, now)
    assert result.txn_count_hour == 2
    assert result.txn_count_day == 2
    assert result.within_limits is True


async def test_exceeding_hourly_limit_is_detected(redis) -> None:
    now = datetime.now(UTC)
    limits = VelocityLimits(max_txn_per_hour=2, max_txn_per_day=10)

    for _ in range(2):
        await record_transaction(redis, "mnd-1", now)

    result = await check_velocity(redis, "mnd-1", limits, now)
    assert result.within_limits is False
    assert result.txn_count_hour == 2


async def test_different_mandates_have_independent_counters(redis) -> None:
    now = datetime.now(UTC)
    limits = VelocityLimits(max_txn_per_hour=1, max_txn_per_day=10)

    await record_transaction(redis, "mnd-1", now)

    result_1 = await check_velocity(redis, "mnd-1", limits, now)
    result_2 = await check_velocity(redis, "mnd-2", limits, now)
    assert result_1.within_limits is False
    assert result_2.within_limits is True


async def test_checking_does_not_itself_record(redis) -> None:
    now = datetime.now(UTC)
    limits = VelocityLimits(max_txn_per_hour=1, max_txn_per_day=10)

    await check_velocity(redis, "mnd-1", limits, now)
    await check_velocity(redis, "mnd-1", limits, now)

    result = await check_velocity(redis, "mnd-1", limits, now)
    assert result.txn_count_hour == 0
