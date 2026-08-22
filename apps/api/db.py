"""Async SQLAlchemy engine/session construction.

No module-level mutable singleton: the engine is built by :func:`get_engine`
(cached per-settings) and sessions are handed out via :func:`get_db_session`,
a FastAPI dependency, so tests can override it with a different engine.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from functools import lru_cache
from pathlib import Path

from sqlalchemy import event
from sqlalchemy.engine import make_url
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


def _ensure_sqlite_parent_dir(database_url: str) -> None:
    """A file-backed SQLite URL (the zero-Docker default — see
    `.env.example`) fails with an opaque "unable to open database file" if
    its parent directory (`.local/` by default) doesn't exist yet, which is
    exactly the state of a fresh clone. Postgres/`:memory:` URLs have no such
    directory to create, so this is a no-op for them."""
    url = make_url(database_url)
    if url.drivername.startswith("sqlite") and url.database and url.database != ":memory:":
        Path(url.database).parent.mkdir(parents=True, exist_ok=True)


def enable_sqlite_foreign_keys(engine: AsyncEngine) -> None:
    """SQLite silently ignores every `ForeignKey(...)` declared in
    `models/tables.py` unless `PRAGMA foreign_keys=ON` is set per connection
    — it is off by default for backwards compatibility, unlike Postgres,
    which always enforces foreign keys. Without this, a row with a dangling
    foreign key (e.g. a `DecisionRow` pointing at a `cart_id` that doesn't
    exist) inserts cleanly against SQLite — the zero-Docker default this
    project's own tests and CLI run against — and would only be caught
    later, in production, against Postgres. A no-op for non-SQLite engines.
    """
    if not engine.sync_engine.dialect.name.startswith("sqlite"):
        return

    @event.listens_for(engine.sync_engine, "connect")
    def _set_sqlite_pragma(dbapi_connection: object, _connection_record: object) -> None:
        cursor = dbapi_connection.cursor()  # type: ignore[attr-defined]
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()


@lru_cache(maxsize=1)
def get_engine() -> AsyncEngine:
    """Build (once) the async engine for the configured database.

    Reads settings via the cached :func:`get_settings` accessor rather than
    taking a ``Settings`` parameter directly — ``Settings`` (a Pydantic model)
    is not hashable, so it cannot itself be an ``lru_cache`` key.

    Outputs: a pooled :class:`AsyncEngine`.
    Failure cases: an invalid ``DATABASE_URL`` raises at first connection, not
        at engine construction (SQLAlchemy engines are lazy).
    """
    settings = get_settings()
    _ensure_sqlite_parent_dir(settings.database_url)
    engine = create_async_engine(settings.database_url, pool_pre_ping=True)
    enable_sqlite_foreign_keys(engine)
    return engine


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
