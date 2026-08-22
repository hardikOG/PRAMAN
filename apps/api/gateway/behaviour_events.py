"""A shared, per-agent event stream that both the storefront (Phase 3, on
every quote request) and the gateway itself (on every authorize attempt)
write to. S3 (stage_behaviour.py) reads it back to compute burst, loop, and
price-probe signals — one stream, two writers, matching the fact that a
probe attack is only visible by comparing quote activity against purchase
activity, which no single component sees on its own.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Literal

from redis.asyncio import Redis

EventType = Literal["quote_requested", "cart_submitted"]


@dataclass(frozen=True)
class AgentEvent:
    """One recorded event, as read back from the stream."""

    event_type: EventType
    at: datetime
    cart_signature: str


def _stream_key(agent_id: str) -> str:
    return f"praman:events:{agent_id}"


async def record_agent_event(
    redis: Redis,
    agent_id: str,
    event_type: EventType,
    at: datetime,
    *,
    cart_signature: str = "",
    maxlen: int,
) -> None:
    """Append one event, trimming the stream to its last `maxlen` entries.

    Complexity: O(1) amortized (approximate trimming via `MAXLEN ~`).
    """
    await redis.xadd(
        _stream_key(agent_id),
        {"type": event_type, "ts": at.timestamp(), "cart_sig": cart_signature},
        maxlen=maxlen,
        approximate=True,
    )


async def get_recent_events(redis: Redis, agent_id: str, *, since: datetime) -> list[AgentEvent]:
    """Return every recorded event for `agent_id` at or after `since`,
    oldest first.

    Reads the whole (maxlen-bounded) stream and filters in Python by our own
    `ts` field, rather than trying to map `since` onto a Redis Stream ID —
    simpler and correct at the stream sizes this bounds us to (hundreds of
    entries per agent).
    Complexity: O(n) in the stream's current length.
    """
    entries = await redis.xrange(_stream_key(agent_id), min="-", max="+")
    since_ts = since.timestamp()
    events = []
    for _entry_id, fields in entries:
        ts = float(fields["ts"])
        if ts >= since_ts:
            events.append(
                AgentEvent(
                    event_type=fields["type"],
                    at=datetime.fromtimestamp(ts, tz=UTC),
                    cart_signature=fields.get("cart_sig", ""),
                )
            )
    return events


def cart_signature(sku_quantities: list[tuple[str, int]]) -> str:
    """A stable signature for "the same cart contents", used to detect the
    repeated-cart loop signal. Order-independent (sorted) so equivalent
    carts submitted with items in a different order still match."""
    return ";".join(f"{sku}:{qty}" for sku, qty in sorted(sku_quantities))
