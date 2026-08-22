"""Async SQLAlchemy engine/session construction.

No module-level mutable singleton: the engine is built by :func:`get_engine`
(cached per-settings) and sessions are handed out via :func:`get_db_session`,
a FastAPI dependency, so tests can override it with a different engine.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from functools import lru_cache

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase

from apps.api.config import get_settings


class Base(DeclarativeBase):
    """Declarative base for all ORM models (see apps/api/models/)."""


@lru_cache(maxsize=1)
def get_engine() -> AsyncEngine:
    """Build (once) the async engine for the configured Postgres database.

    Reads settings via the cached :func:`get_settings` accessor rather than
    taking a ``Settings`` parameter directly — ``Settings`` (a Pydantic model)
    is not hashable, so it cannot itself be an ``lru_cache`` key.

    Outputs: a pooled :class:`AsyncEngine`.
    Failure cases: an invalid ``DATABASE_URL`` raises at first connection, not
        at engine construction (SQLAlchemy engines are lazy).
    """
    settings = get_settings()
    return create_async_engine(settings.database_url, pool_pre_ping=True)


def get_sessionmaker() -> async_sessionmaker[AsyncSession]:
    """Return a session factory bound to the shared engine.

    Complexity: O(1); does not open a connection.
    """
    return async_sessionmaker(bind=get_engine(), expire_on_commit=False)


async def get_db_session() -> AsyncIterator[AsyncSession]:
    """FastAPI dependency yielding a request-scoped `AsyncSession`.

    Outputs: an `AsyncSession`, committed on clean exit, rolled back on
        exception, and always closed.
    Failure cases: re-raises any exception after rolling back the transaction.
    """
    sessionmaker = get_sessionmaker()
    async with sessionmaker() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
