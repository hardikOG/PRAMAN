"""Redis client construction.

Cached accessor, not a module-level mutable singleton: `redis.asyncio.Redis`
is itself connection-pooled and safe to share, so one client is built and
reused via :func:`get_redis`.

A `REDIS_URL` of exactly `fake://local` selects an in-process
`fakeredis.FakeAsyncRedis` instead of a real connection — this is what lets
`praman seed`/`praman demo` (and this project's own local development on a
machine where Docker is unavailable) run genuinely end to end with zero
external services, not just under pytest. Anything else is passed straight
to `redis.asyncio.from_url` unchanged; production always uses a real Redis
via `docker-compose.yml`.
"""

from __future__ import annotations

from functools import lru_cache

import redis.asyncio as redis
from fakeredis import FakeAsyncRedis

from apps.api.config import get_settings

_FAKE_REDIS_URL = "fake://local"


@lru_cache(maxsize=1)
def get_redis() -> redis.Redis:
    """Return the process-wide Redis client, constructed once and cached.

    Outputs: a `redis.asyncio.Redis`-compatible client bound to `REDIS_URL`,
        decoding responses as UTF-8 strings.
    Failure cases: connection errors surface on first command, not here —
        the client is lazy.
    """
    settings = get_settings()
    if settings.redis_url == _FAKE_REDIS_URL:
        return FakeAsyncRedis(decode_responses=True)
    return redis.from_url(settings.redis_url, decode_responses=True)
