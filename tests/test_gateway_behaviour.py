"""S3 behaviour stage: burst, price-probe, and repeated-cart-loop signals,
plus the shared event-stream primitives they're built on."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from apps.api.gateway.behaviour_events import (
    cart_signature,
    get_recent_events,
    record_agent_event,
)
from apps.api.gateway.stage_behaviour import evaluate_behaviour
from fakeredis import FakeAsyncRedis

_THRESHOLDS = {
    "max_req_per_sec": 5.0,
    "burst_window_seconds": 10.0,
    "probe_window_seconds": 300.0,
    "probe_min_quotes": 5,
    "loop_min_repeats": 3,
}


@pytest.fixture
async def redis():
    client = FakeAsyncRedis(decode_responses=True)
    yield client
    await client.aclose()


def test_cart_signature_is_order_independent() -> None:
    a = cart_signature([("NR-A9", 1), ("SP-BLK", 2)])
    b = cart_signature([("SP-BLK", 2), ("NR-A9", 1)])
    assert a == b


def test_cart_signature_differs_for_different_contents() -> None:
    a = cart_signature([("NR-A9", 1)])
    b = cart_signature([("NR-A9", 2)])
    assert a != b


async def test_recorded_events_round_trip(redis) -> None:
    now = datetime.now(UTC)
    await record_agent_event(redis, "agt-1", "quote_requested", now, maxlen=500)
    events = await get_recent_events(redis, "agt-1", since=now - timedelta(seconds=1))
    assert len(events) == 1
    assert events[0].event_type == "quote_requested"


async def test_no_signals_for_a_quiet_agent(redis) -> None:
    result = await evaluate_behaviour(
        redis, "agt-quiet", datetime.now(UTC), cart_signature="sig", **_THRESHOLDS
    )
    assert result.score == 0.0
    assert result.signals == []


async def test_burst_request_rate_is_detected(redis) -> None:
    # 60 events inside the 10s burst window averages 6 req/sec, over the
    # 5 req/sec threshold in _THRESHOLDS.
    now = datetime.now(UTC)
    for i in range(60):
        await record_agent_event(
            redis, "agt-burst", "cart_submitted", now - timedelta(seconds=i * 0.05), maxlen=500
        )
    result = await evaluate_behaviour(redis, "agt-burst", now, cart_signature="", **_THRESHOLDS)
    assert "burst_request_rate" in result.signals
    assert result.score > 0


async def test_price_probe_pattern_is_detected(redis) -> None:
    now = datetime.now(UTC)
    for i in range(6):
        await record_agent_event(
            redis, "agt-probe", "quote_requested", now - timedelta(seconds=i * 20), maxlen=500
        )
    result = await evaluate_behaviour(redis, "agt-probe", now, cart_signature="", **_THRESHOLDS)
    assert "price_probe_pattern" in result.signals


async def test_price_probe_not_flagged_once_a_purchase_happens(redis) -> None:
    now = datetime.now(UTC)
    for i in range(6):
        await record_agent_event(
            redis, "agt-buyer", "quote_requested", now - timedelta(seconds=i * 20), maxlen=500
        )
    await record_agent_event(redis, "agt-buyer", "cart_submitted", now, maxlen=500)
    result = await evaluate_behaviour(redis, "agt-buyer", now, cart_signature="", **_THRESHOLDS)
    assert "price_probe_pattern" not in result.signals


async def test_repeated_cart_loop_is_detected(redis) -> None:
    now = datetime.now(UTC)
    sig = cart_signature([("NR-A9", 1)])
    for i in range(4):
        await record_agent_event(
            redis,
            "agt-loop",
            "cart_submitted",
            now - timedelta(seconds=i * 30),
            cart_signature=sig,
            maxlen=500,
        )
    result = await evaluate_behaviour(redis, "agt-loop", now, cart_signature=sig, **_THRESHOLDS)
    assert "repeated_cart_loop" in result.signals


async def test_different_agents_are_independent(redis) -> None:
    now = datetime.now(UTC)
    for i in range(20):
        await record_agent_event(
            redis, "agt-noisy", "cart_submitted", now - timedelta(seconds=i * 0.1), maxlen=500
        )
    result = await evaluate_behaviour(redis, "agt-quiet-2", now, cart_signature="", **_THRESHOLDS)
    assert result.signals == []
