"""Redis client construction.

Cached accessor, not a module-level mutable singleton: `redis.asyncio.Redis` is
itself connection-pooled and safe to share, so one client is built and reused
via :func:`get_redis`.
"""

from __future__ import annotations

from functools import lru_cache

import redis.asyncio as redis

from apps.api.config import get_settings


@lru_cache(maxsize=1)
def get_redis() -> redis.Redis:
    """Return the process-wide Redis client, constructed once and cached.

    Outputs: a `redis.asyncio.Redis` bound to `REDIS_URL`, decoding responses
        as UTF-8 strings.
    Failure cases: connection errors surface on first command, not here —
        the client is lazy.
    """
    settings = get_settings()
    return redis.from_url(settings.redis_url, decode_responses=True)
