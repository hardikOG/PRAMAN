"""Shared fixtures for route-level integration tests: a FastAPI TestClient
wired to an in-memory SQLite DB, an isolated fakeredis instance, and a
temp-file ledger signing key — no live Postgres/Redis, no shared state with
`praman demo`'s own `.keys/`/`.local/` files.
"""

from __future__ import annotations

import pytest
from apps.api.db import Base, get_db_session
from apps.api.ledger.crypto import load_or_create_signing_key
from apps.api.main import create_app
from apps.api.routes import playground as playground_module
from fakeredis import FakeAsyncRedis
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine


@pytest.fixture
async def client(tmp_path, monkeypatch):
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    sessionmaker = async_sessionmaker(bind=engine, expire_on_commit=False)

    async def override_get_db_session():
        async with sessionmaker() as session:
            yield session
            await session.commit()

    redis = FakeAsyncRedis(decode_responses=True)
    monkeypatch.setattr(playground_module, "get_redis", lambda: redis)

    key_path = tmp_path / "ledger_key.pem"
    monkeypatch.setattr(
        playground_module,
        "load_or_create_signing_key",
        lambda _p: load_or_create_signing_key(str(key_path)),
    )

    app = create_app()
    app.dependency_overrides[get_db_session] = override_get_db_session
    with TestClient(app) as c:
        yield c
    await engine.dispose()
