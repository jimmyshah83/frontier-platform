"""
STDIO MCP Server for Content Understanding

Run this for local testing with MCP Inspector.
Uses stdio transport which MCP Inspector supports natively.
"""

import asyncio
import logging

from dotenv import load_dotenv
from mcp.server.stdio import stdio_server

from .mcp_server import create_mcp_server

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


async def main():
    """Run the MCP server with stdio transport."""
    load_dotenv()
    
    server = create_mcp_server()
    
    async with stdio_server() as (read_stream, write_stream):
        await server.run(
            read_stream,
            write_stream,
            server.create_initialization_options(),
        )


if __name__ == "__main__":
    asyncio.run(main())
