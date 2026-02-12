"""
Azure Functions ASGI wrapper for the Customer Order Assistant MCP Server.

Wraps the FastMCP streamable-http ASGI app in Azure Functions.
Key-based auth is handled by Azure Functions (AuthLevel.FUNCTION).
"""

import azure.functions as func
from mcp_server import mcp

app = func.AsgiFunctionApp(
    app=mcp.streamable_http_app(),
    http_auth_level=func.AuthLevel.FUNCTION,
)
