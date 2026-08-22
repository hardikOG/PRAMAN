"""FastAPI application entrypoint.

Routers: health/readiness (Phase 0), the playground (Phase 7 — issues a
mandate and runs one preset cart through the full pipeline), and decisions
(the console's Ledger feed and proof inspector).
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from apps.api.config import get_settings
from apps.api.db import Base, get_engine
from apps.api.logging import configure_logging, get_logger
from apps.api.routes.decisions import router as decisions_router
from apps.api.routes.eval_results import router as eval_results_router
from apps.api.routes.health import router as health_router
from apps.api.routes.playground import router as playground_router

logger = get_logger(__name__)


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    """Configure structured logging and ensure tables exist at process
    startup.

    `create_all` is a no-op against tables that already exist (checked via
    `IF NOT EXISTS`), so this is safe to run on every startup — it just
    means starting the API alone, with no prior `praman seed`, doesn't 500
    on the first request with a confusing "no such table" error (further
    confused by Starlette dropping CORS headers on an unhandled exception,
    which reads as a CORS bug in the browser console rather than the real
    missing-table one)."""
    settings = get_settings()
    configure_logging(settings.log_level)
    engine = get_engine()
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    logger.info("praman.api.startup", env=settings.praman_env)
    yield
    logger.info("praman.api.shutdown")


def create_app() -> FastAPI:
    """Construct the FastAPI application.

    Outputs: a configured `FastAPI` instance with routers mounted.
    Failure cases: none — construction is side-effect-free beyond registering
        routes; the lifespan handler is what touches logging/config.
    """
    app = FastAPI(
        title="PRAMAN",
        description="Verifiable authorization for agent-initiated payments.",
        version="0.1.0",
        lifespan=lifespan,
    )
    # The console (Vite dev server, a different origin) is the only client —
    # a wide-open CORS policy is fine for this local-only demo surface.
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.include_router(health_router)
    app.include_router(playground_router)
    app.include_router(decisions_router)
    app.include_router(eval_results_router)
    return app


app = create_app()
