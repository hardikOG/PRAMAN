"""Liveness/readiness endpoints.

Split into two so the compose healthcheck (`/health`) never depends on
Postgres/Redis being reachable — that would create a startup deadlock where
the container is marked unhealthy while its dependencies are still coming up.
`/health/ready` is the deeper check for the console and ops tooling.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.db import get_db_session
from apps.api.redis_client import get_redis

router = APIRouter(tags=["health"])


@router.get("/health")
async def health() -> dict[str, str]:
    """Liveness probe: the process is up and serving requests.

    Outputs: `{"status": "ok"}`. Never touches Postgres or Redis.
    """
    return {"status": "ok"}


@router.get("/health/ready")
async def readiness(session: AsyncSession = Depends(get_db_session)) -> dict[str, str]:
    """Readiness probe: dependencies (Postgres, Redis) are reachable.

    Inputs: injected DB session.
    Outputs: `{"status": "ok", "postgres": "ok", "redis": "ok"}`.
    Failure cases: raises (surfaced as a 500 by FastAPI) if either dependency
        is unreachable — callers should treat that as "not ready", not "down".
    Complexity: O(1) — one trivial query, one PING.
    """
    await session.execute(text("SELECT 1"))
    redis_client = get_redis()
    await redis_client.ping()
    return {"status": "ok", "postgres": "ok", "redis": "ok"}
