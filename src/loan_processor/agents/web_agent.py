"""``maf-web-agent`` — a single Foundry PromptAgent with a Tavily MCP tool.

This module creates (and keeps up to date) a server-side **PromptAgent** in the
Foundry project so the agent is visible in the Foundry portal under *Agents*.
A purely local ``Agent`` wrapper would never appear in the portal — only an
agent version persisted through ``project_client.agents.create_version`` does.

The agent's only tool is the **Tavily MCP server**, referenced through the
existing ``TavilyMCP`` project connection (``project_connection_id``). Foundry
forbids passing raw ``Authorization`` headers on MCP tools, so key-based auth is
supplied through the project connection (which stores the key as ``CustomKeys``)
rather than embedded here — access is governed by the caller's RBAC.

Run it directly to create/update the agent and (optionally) ask it a question::

    # Register / update the agent in Foundry, then exit
    uv run python -m loan_processor.agents.web_agent

    # Register and run a one-off query against it
    uv run python -m loan_processor.agents.web_agent --query "Latest US 30y mortgage rate?"
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import os

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Agent configuration
# ---------------------------------------------------------------------------

AGENT_NAME = os.environ.get("WEB_AGENT_NAME", "maf-web-agent")

#: Name of the existing Foundry connection that fronts the Tavily MCP server.
TAVILY_CONNECTION_NAME = os.environ.get("TAVILY_MCP_CONNECTION_NAME", "TavilyMCP")


def _mcp_server_label() -> str:
    return os.environ.get("TAVILY_MCP_SERVER_LABEL", "tavily")

AGENT_INSTRUCTIONS = """\
You are a web research assistant. Use the Tavily web-search MCP tool to find
current, factual information and answer the user's question.

Guidelines:
- Always call the Tavily tool for anything time-sensitive, factual, or that you
  are not fully certain about from memory.
- Synthesize the results into a concise, well-structured answer.
- Cite the source URLs you relied on.
"""


# ---------------------------------------------------------------------------
# Foundry helpers
# ---------------------------------------------------------------------------


def _require_env(*names: str) -> str:
    for name in names:
        value = os.environ.get(name)
        if value:
            return value
    raise RuntimeError(
        f"None of these environment variables are set: {', '.join(names)}"
    )


def _project_endpoint() -> str:
    return _require_env("FOUNDRY_PROJECT_ENDPOINT", "AZURE_AI_PROJECT_ENDPOINT")


def _model() -> str:
    return _require_env("FOUNDRY_MODEL", "AZURE_AI_MODEL_DEPLOYMENT")


def _project_client():
    """Return an authenticated ``AIProjectClient`` (Azure CLI credential)."""
    from azure.ai.projects import AIProjectClient
    from azure.identity import AzureCliCredential

    return AIProjectClient(
        endpoint=_project_endpoint(),
        credential=AzureCliCredential(),
    )


def _resolve_tavily_connection(project_client):
    """Return ``(connection_id, target_url)`` for the Tavily MCP connection.

    Foundry requires MCP tools that need credentials to reference a project
    connection (``project_connection_id``) rather than carrying raw auth
    headers. The connection itself stores the key, so nothing secret lives here.
    """
    conn = project_client.connections.get(TAVILY_CONNECTION_NAME)
    connection_id = getattr(conn, "id", None)
    target = getattr(conn, "target", None) or os.environ.get("TAVILY_MCP_URL")
    if not connection_id:
        raise RuntimeError(
            f"Connection {TAVILY_CONNECTION_NAME!r} has no id; cannot attach MCP tool."
        )
    if not target:
        raise RuntimeError(
            f"Connection {TAVILY_CONNECTION_NAME!r} has no target URL; "
            "set TAVILY_MCP_URL to the MCP server endpoint."
        )
    return connection_id, target


def _build_definition(project_client):
    """Build the PromptAgent definition with the Tavily MCP tool attached.

    The MCP server is reached through the ``TavilyMCP`` project connection.
    Both ``server_url`` (the connection target) and ``project_connection_id``
    are supplied: the URL alone or the connection alone fails at invocation.
    """
    from azure.ai.projects.models import MCPTool, PromptAgentDefinition

    connection_id, target = _resolve_tavily_connection(project_client)

    tavily_tool = MCPTool(
        server_label=_mcp_server_label(),
        server_url=target,
        project_connection_id=connection_id,
        # Autonomous backend agent: don't pause for human tool approval.
        require_approval="never",
    )

    return PromptAgentDefinition(
        model=_model(),
        instructions=AGENT_INSTRUCTIONS,
        tools=[tavily_tool],
    )


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def ensure_agent(project_client=None):
    """Create or update ``maf-web-agent`` in Foundry. Returns the agent version.

    Idempotent: each call publishes a new version of the same named agent rather
    than creating a duplicate, so the portal shows a single ``maf-web-agent``
    entry with an incrementing version history.
    """
    own_client = project_client is None
    client = project_client or _project_client()
    try:
        definition = _build_definition(client)
        version = client.agents.create_version(
            agent_name=AGENT_NAME,
            definition=definition,
            description="MAF web-research agent using the Tavily MCP tool.",
        )
        logger.info(
            "Published Foundry agent %r version %s",
            AGENT_NAME,
            getattr(version, "version", "?"),
        )
        return version
    finally:
        if own_client:
            client.close()


async def run_agent(query: str) -> str:
    """Invoke the (already-registered) Foundry agent with a single query."""
    from agent_framework.foundry import FoundryAgent
    from azure.identity import AzureCliCredential

    async with FoundryAgent(
        project_endpoint=_project_endpoint(),
        agent_name=AGENT_NAME,
        credential=AzureCliCredential(),
    ) as agent:
        response = await agent.run(query)
        return getattr(response, "text", None) or str(response)


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------


def _main() -> int:
    try:
        from dotenv import load_dotenv

        load_dotenv()
    except Exception:  # pragma: no cover
        pass

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")

    parser = argparse.ArgumentParser(
        description="Create/update the maf-web-agent in Foundry and optionally query it."
    )
    parser.add_argument(
        "--query",
        help="If provided, run this question against the agent after registering it.",
    )
    parser.add_argument(
        "--skip-register",
        action="store_true",
        help="Don't (re)create the agent; just run the query against the existing one.",
    )
    args = parser.parse_args()

    if not args.skip_register:
        version = ensure_agent()
        ver = getattr(version, "version", "?")
        print(f"\u2705 Foundry agent '{AGENT_NAME}' is registered (version {ver}).")
        print(f"   Project: {_project_endpoint()}")
        print("   It now appears in the Foundry portal under Agents.\n")

    if args.query:
        print(f"\u25b6 Query: {args.query}\n")
        answer = asyncio.run(run_agent(args.query))
        print(answer)

    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(_main())
