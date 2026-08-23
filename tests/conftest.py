"""Shared fixtures for route-level integration tests: a FastAPI TestClient
wired to an in-memory SQLite DB, an isolated fakeredis instance, and a
temp-file ledger signing key — no live Postgres/Redis, no shared state with
`praman demo`'s own `.keys/`/`.local/` files.
"""

from __future__ import annotations

import pytest
from apps.api.db import Base, enable_sqlite_foreign_keys, get_db_session
from apps.api.ledger.crypto import load_or_create_signing_key
from apps.api.main import create_app
from apps.api.routes import decisions as decisions_module
from apps.api.routes import playground as playground_module
from fakeredis import FakeAsyncRedis
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine


@pytest.fixture
async def client(tmp_path, monkeypatch):
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    enable_sqlite_foreign_keys(engine)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    sessionmaker = async_sessionmaker(bind=engine, expire_on_commit=False)

    async def override_get_db_session():
        async with sessionmaker() as session:
            yield session
            await session.commit()

    # One shared fake Redis and one shared ledger key across playground.py
    # and decisions.py: a step-up token issued by /playground/run has to be
    # redeemable by /decisions/step-up/confirm in the same test, and a
    # confirmed decision's proof bundle has to chain against the same
    # ledger key an earlier ALLOW in the same test signed with.
    redis = FakeAsyncRedis(decode_responses=True)
    key_path = tmp_path / "ledger_key.pem"
    patched_key_loader = lambda _p: load_or_create_signing_key(str(key_path))  # noqa: E731

    for module in (playground_module, decisions_module):
        monkeypatch.setattr(module, "get_redis", lambda: redis)
        monkeypatch.setattr(module, "load_or_create_signing_key", patched_key_loader)

    app = create_app()
    app.dependency_overrides[get_db_session] = override_get_db_session
    with TestClient(app) as c:
        yield c
    await engine.dispose()
