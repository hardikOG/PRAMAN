"""Agent Storefront MCP server: exposes `search_products`, `get_product`,
`request_quote`, `submit_cart`, `get_order_status` over streamable HTTP.

Tool logic lives in `tools.py` so it's testable by calling those functions
directly, with no MCP client/session needed.
"""

from __future__ import annotations

from mcp.server import MCPServer
from starlette.requests import Request
from starlette.responses import JSONResponse

from apps.api.config import get_settings
from apps.api.logging import configure_logging, get_logger
from apps.mcp_storefront import tools

logger = get_logger(__name__)


def create_app() -> MCPServer:
    """Construct the storefront MCP server with all five tools registered."""
    settings = get_settings()
    configure_logging(settings.log_level)

    app = MCPServer(name="praman-storefront", version="0.1.0")

    @app.custom_route("/health", methods=["GET"])
    async def health(_request: Request) -> JSONResponse:
        return JSONResponse({"status": "ok"})

    app.add_tool(tools.search_products)
    app.add_tool(tools.get_product)
    app.add_tool(tools.request_quote)
    app.add_tool(tools.submit_cart)
    app.add_tool(tools.get_order_status)

    return app


app = create_app()

if __name__ == "__main__":
    import asyncio

    logger.info("praman.mcp_storefront.startup")
    asyncio.run(app.run_streamable_http_async(host="0.0.0.0", port=8001))
