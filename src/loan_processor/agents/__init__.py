"""Foundry agents built with the Microsoft Agent Framework.

Currently exposes ``maf-web-agent`` — a single PromptAgent that uses the
Tavily MCP tool (via the project's ``TavilyMCP`` connection) for web search.
"""

from .web_agent import (
    AGENT_NAME,
    ensure_agent,
    run_agent,
)

__all__ = ["AGENT_NAME", "ensure_agent", "run_agent"]
