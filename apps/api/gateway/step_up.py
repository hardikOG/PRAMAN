"""Step-up tokens: the one-tap human-confirm link a STEP_UP decision issues.

A token is a single-use Redis key mapping to the decision it confirms, with
a TTL (`STEP_UP_TTL_SECONDS`, default 15 minutes) — after that window, the
human's confirm link is dead and the agent must re-authorize from scratch
rather than resurrect a stale decision.
"""

from __future__ import annotations

import uuid

from redis.asyncio import Redis


def _token_key(token: str) -> str:
    return f"praman:stepup:{token}"


async def issue_step_up_token(redis: Redis, decision_id: str, *, ttl_seconds: int) -> str:
    """Issue a fresh step-up token for `decision_id`.

    Complexity: O(1) — one Redis SET with an expiry.
    """
    token = uuid.uuid4().hex
    await redis.set(_token_key(token), decision_id, ex=ttl_seconds)
    return token


async def peek_step_up_token(redis: Redis, token: str) -> tuple[str, int] | None:
    """Read a step-up token without consuming it: returns `(decision_id,
    seconds_remaining)`, or `None` if it doesn't exist or has expired.

    Exists so a shopper-facing screen can show *what* is being confirmed
    before anything irreversible happens — redemption (`GETDEL`) stays the
    single point where a token is spent, so peeking can never let one be
    used twice. Complexity: O(1), two Redis round trips.
    """
    key = _token_key(token)
    decision_id = await redis.get(key)
    if decision_id is None:
        return None
    return decision_id, max(int(await redis.ttl(key)), 0)


async def redeem_step_up_token(redis: Redis, token: str) -> str | None:
    """Atomically fetch and delete a step-up token, returning the decision
    id it confirmed, or `None` if the token doesn't exist or already expired.

    Single-use by construction: `GETDEL` removes the key in the same round
    trip that reads it, so the same token can never confirm twice.
    Complexity: O(1).
    """
    return await redis.getdel(_token_key(token))
