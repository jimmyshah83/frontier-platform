"""
Local HTTP MCP Server for Content Understanding

Run this server locally for testing with MCP Inspector or agents.
Uses the Streamable HTTP transport for MCP.
"""

import contextlib
import logging
import os

from dotenv import load_dotenv
from mcp.server.streamable_http_manager import StreamableHTTPSessionManager
from starlette.applications import Starlette
from starlette.middleware.cors import CORSMiddleware
from starlette.routing import Mount, Route
from starlette.responses import JSONResponse
from starlette.types import Receive, Scope, Send
import uvicorn

from .mcp_server import create_mcp_server

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


async def health_check(request):
    """Health check endpoint."""
    return JSONResponse({
        "status": "healthy",
        "service": "content-understanding-mcp",
        "transport": "streamable-http",
    })


def create_app() -> Starlette:
    """Create the Starlette app with MCP server."""
    load_dotenv()

    # Create MCP server
    mcp_server = create_mcp_server()

    # Create the session manager with stateless mode for scalability
    session_manager = StreamableHTTPSessionManager(
        app=mcp_server,
        json_response=True,  # Use JSON responses instead of SSE
        stateless=True,  # Stateless mode for Container Apps
    )

    # ASGI handler for streamable HTTP connections
    async def handle_streamable_http(scope: Scope, receive: Receive, send: Send) -> None:
        await session_manager.handle_request(scope, receive, send)

    @contextlib.asynccontextmanager
    async def lifespan(app: Starlette):
        """Lifespan context manager for the Starlette app."""
        logger.info("Starting Content Understanding MCP Server...")
        async with session_manager.run():
            logger.info("MCP Session Manager started!")
            try:
                yield
            finally:
                logger.info("Shutting down MCP Server...")

    # Create the Starlette app
    starlette_app = Starlette(
        debug=True,
        routes=[
            Route("/health", health_check, methods=["GET"]),
            Mount("/mcp", app=handle_streamable_http),
        ],
        lifespan=lifespan,
    )

    # Wrap with CORS middleware for browser-based clients
    starlette_app = CORSMiddleware(
        starlette_app,
        allow_origins=["*"],
        allow_methods=["GET", "POST", "DELETE"],
        expose_headers=["Mcp-Session-Id"],
    )

    return starlette_app


def main():
    """Run the local MCP server."""
    host = os.getenv("MCP_HOST", "0.0.0.0")
    port = int(os.getenv("MCP_PORT", "8000"))

    logger.info(f"Starting MCP server on http://{host}:{port}")
    logger.info(f"MCP endpoint: http://{host}:{port}/mcp")
    logger.info(f"Health check: http://{host}:{port}/health")

    app = create_app()
    uvicorn.run(app, host=host, port=port)


if __name__ == "__main__":
    main()
