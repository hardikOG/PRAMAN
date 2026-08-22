"""One-time-use enforcement for cart ids — what catches the "mandate replay"
attack (resubmitting a previously authorized cart to charge it twice).

A `Cart.id` is the natural idempotency key here: the storefront mints a
fresh one per quote-to-cart submission, so seeing the same id twice means
the same authorized assertion is being replayed, not a new purchase.
"""

from __future__ import annotations

from redis.asyncio import Redis


def _replay_key(cart_id: str) -> str:
    return f"praman:replay:{cart_id}"


async def check_and_mark_seen(redis: Redis, cart_id: str, *, ttl_seconds: int) -> bool:
    """Atomically check whether `cart_id` has been seen before, marking it
    seen if not.

    Outputs: `True` if this is the first time `cart_id` has been presented
        (the caller should proceed); `False` if it has been seen before
        within `ttl_seconds` (the caller should treat this as a replay).
    Complexity: O(1) — a single `SET ... NX` round-trip.
    """
    was_set = await redis.set(_replay_key(cart_id), "1", nx=True, ex=ttl_seconds)
    return bool(was_set)
