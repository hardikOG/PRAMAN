"""Agent Storefront MCP server entrypoint.

Phase 0 exposes only a health endpoint over plain HTTP so the container and
compose gate can go green. The actual MCP server (catalog, quote, checkout
tools, Razorpay order creation) is built in Phase 3 — see PRAMAN_BUILD.md §9.
This module intentionally does not yet import the `mcp` SDK: there is nothing
for it to serve until the catalog and tools exist.
"""

from __future__ import annotations

from fastapi import FastAPI

from apps.api.config import get_settings
from apps.api.logging import configure_logging, get_logger

logger = get_logger(__name__)


def create_app() -> FastAPI:
    """Construct the Phase-0 placeholder storefront app.

    Outputs: a `FastAPI` instance with a single `/health` route.
    """
    settings = get_settings()
    configure_logging(settings.log_level)
    app = FastAPI(title="PRAMAN Storefront (MCP)", version="0.1.0")

    @app.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    return app


app = create_app()

if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8001)
