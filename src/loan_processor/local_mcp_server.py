"""
Local HTTP MCP Server for Content Understanding

Run this server locally for testing with MCP Inspector or agents.
Uses the Streamable HTTP transport for MCP.
"""

import logging
import os
from contextlib import asynccontextmanager
from uuid import uuid4

from dotenv import load_dotenv
from mcp.server.streamable_http import StreamableHTTPServerTransport
from starlette.applications import Starlette
from starlette.routing import Mount, Route
from starlette.responses import JSONResponse
import uvicorn

from .mcp_server import create_mcp_server

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Store active transports by session ID
transports: dict[str, StreamableHTTPServerTransport] = {}


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

    async def handle_mcp(request):
        """Handle MCP requests using Streamable HTTP transport."""
        # Check for existing session
        session_id = request.headers.get("mcp-session-id")

        if session_id and session_id in transports:
            # Reuse existing transport
            transport = transports[session_id]
        else:
            # Create new transport for this session
            transport = StreamableHTTPServerTransport(
                mcp_session_id=str(uuid4()),
                is_json_response_enabled=True,
            )
            transports[transport.mcp_session_id] = transport

            # Connect transport to server (fire and forget)
            async def run_server():
                await mcp_server.run(
                    transport.read_stream,
                    transport.write_stream,
                    mcp_server.create_initialization_options(),
                )

            import asyncio
            asyncio.create_task(run_server())

        return await transport.handle_request(request)

    async def handle_mcp_sse(request):
        """Handle MCP SSE connections."""
        session_id = request.headers.get("mcp-session-id")
        if session_id and session_id in transports:
            transport = transports[session_id]
            return await transport.handle_sse_request(request)
        return JSONResponse({"error": "No active session"}, status_code=400)

    @asynccontextmanager
    async def lifespan(app: Starlette):
        """Lifespan context manager for the Starlette app."""
        logger.info("Starting Content Understanding MCP Server...")
        yield
        # Cleanup transports
        for transport in transports.values():
            await transport.close()
        transports.clear()
        logger.info("Shutting down MCP Server...")

    routes = [
        Route("/health", health_check, methods=["GET"]),
        Route("/mcp", handle_mcp, methods=["POST", "GET", "DELETE"]),
    ]

    return Starlette(
        debug=True,
        routes=routes,
        lifespan=lifespan,
    )


def main():
    """Run the local MCP server."""
    host = os.getenv("MCP_HOST", "127.0.0.1")
    port = int(os.getenv("MCP_PORT", "8000"))

    logger.info(f"Starting MCP server on http://{host}:{port}")
    logger.info(f"MCP endpoint: http://{host}:{port}/mcp")
    logger.info(f"Health check: http://{host}:{port}/health")

    app = create_app()
    uvicorn.run(app, host=host, port=port)


if __name__ == "__main__":
    main()
