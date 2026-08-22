"""Alembic environment, wired to the app's own settings and async engine so
the database URL is configured in exactly one place (`apps.api.config`).
"""

from __future__ import annotations

import asyncio
from logging.config import fileConfig

from alembic import context
from apps.api import models  # noqa: F401  (registers ORM tables on Base.metadata)
from apps.api.config import get_settings
from apps.api.db import Base, get_engine
from sqlalchemy.ext.asyncio import AsyncEngine

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    """Emit SQL to stdout without a live DB connection (`alembic upgrade --sql`)."""
    settings = get_settings()
    context.configure(
        url=settings.database_url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def _do_run_migrations(connection) -> None:  # type: ignore[no-untyped-def]
    context.configure(connection=connection, target_metadata=target_metadata)
    with context.begin_transaction():
        context.run_migrations()


async def run_migrations_online() -> None:
    """Run migrations against the live async engine."""
    engine: AsyncEngine = get_engine()
    async with engine.connect() as connection:
        await connection.run_sync(_do_run_migrations)
    await engine.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    asyncio.run(run_migrations_online())
