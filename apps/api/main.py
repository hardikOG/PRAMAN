"""FastAPI application entrypoint.

Phase 0 exposes only health/readiness so the container and compose gate can go
green before any domain logic exists. Routers for mandates, gateway decisions,
and the ledger are mounted in `apps/api/routes/` starting Phase 2.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from apps.api.config import get_settings
from apps.api.logging import configure_logging, get_logger
from apps.api.routes.health import router as health_router

logger = get_logger(__name__)


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    """Configure structured logging once at process startup."""
    settings = get_settings()
    configure_logging(settings.log_level)
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
    app.include_router(health_router)
    return app


app = create_app()
