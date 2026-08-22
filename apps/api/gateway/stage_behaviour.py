"""S3 — behavioural anomaly scoring. Independent of anything the mandate
declares: burst request rate, a price-probe pattern (many quotes, no
purchase), and a repeated-cart loop, computed from the shared agent event
stream (behaviour_events.py). This is what catches a "velocity drain" —
many individually in-policy purchases that S1's per-mandate hour/day caps
don't flag on their own — as a rate anomaly instead.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from datetime import datetime, timedelta

from redis.asyncio import Redis

from apps.api.gateway.behaviour_events import get_recent_events


@dataclass(frozen=True)
class BehaviourResult:
    """S3's verdict: an anomaly score in [0, 1], the named signals that
    fired (for the decision trace / audit), and latency."""

    score: float
    signals: list[str]
    latency_ms: float


async def evaluate_behaviour(
    redis: Redis,
    agent_id: str,
    at: datetime,
    *,
    cart_signature: str,
    max_req_per_sec: float,
    burst_window_seconds: float,
    probe_window_seconds: float,
    probe_min_quotes: int,
    loop_min_repeats: int,
) -> BehaviourResult:
    """Score `agent_id`'s recent activity for burst, probe, and loop
    patterns.

    Complexity: O(n) in the number of recent events (bounded by the event
    stream's `maxlen`, so effectively O(1) at steady state) plus one Redis
    `XRANGE` round-trip.
    """
    start = time.perf_counter()
    lookback = max(burst_window_seconds, probe_window_seconds)
    events = await get_recent_events(redis, agent_id, since=at - timedelta(seconds=lookback))

    signals: list[str] = []
    score = 0.0

    burst_cutoff = at - timedelta(seconds=burst_window_seconds)
    burst_count = sum(1 for e in events if e.at >= burst_cutoff)
    if burst_window_seconds > 0 and (burst_count / burst_window_seconds) > max_req_per_sec:
        signals.append("burst_request_rate")
        score = max(score, 0.6)

    probe_cutoff = at - timedelta(seconds=probe_window_seconds)
    window_events = [e for e in events if e.at >= probe_cutoff]
    quote_count = sum(1 for e in window_events if e.event_type == "quote_requested")
    purchase_count = sum(1 for e in window_events if e.event_type == "cart_submitted")
    if quote_count >= probe_min_quotes and purchase_count == 0:
        signals.append("price_probe_pattern")
        score = max(score, 0.5)

    repeated_cart_count = sum(
        1
        for e in window_events
        if e.event_type == "cart_submitted" and e.cart_signature == cart_signature
    )
    if cart_signature and repeated_cart_count >= loop_min_repeats:
        signals.append("repeated_cart_loop")
        score = max(score, 0.5)

    return BehaviourResult(
        score=score, signals=signals, latency_ms=(time.perf_counter() - start) * 1000
    )
