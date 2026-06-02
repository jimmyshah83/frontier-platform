"""``maf-web-agent`` — a single Foundry PromptAgent with a Tavily MCP tool.

This module creates (and keeps up to date) a server-side **PromptAgent** in the
Foundry project so the agent is visible in the Foundry portal under *Agents*.
A purely local ``Agent`` wrapper would never appear in the portal — only an
agent version persisted through ``project_client.agents.create_version`` does.

The agent's only tool is the **Tavily MCP server**, referenced through the
existing ``TavilyMCP`` project connection (``project_connection_id``). The
connection stores its own API key (``CustomKeys``), so no raw key is embedded
here — access is governed by the caller's RBAC on the project.

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

#: Label the model sees when calling the MCP server.
MCP_SERVER_LABEL = os.environ.get("TAVILY_MCP_SERVER_LABEL", "tavily")

#: Project connection that fronts the Tavily MCP server (stores the API key).
TAVILY_CONNECTION_NAME = os.environ.get("TAVILY_CONNECTION_NAME", "TavilyMCP")

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


def _resolve_tavily_connection(project_client) -> tuple[str, str]:
    """Resolve the TavilyMCP connection to ``(connection_id, server_url)``.

    The connection supplies the MCP endpoint (``target``) and stores the API
    key (``CustomKeys``); we pass both the id (for auth) and the url (required
    by the Responses API at invocation time).
    """
    conn = project_client.connections.get(TAVILY_CONNECTION_NAME)
    conn_id = getattr(conn, "id", None) or TAVILY_CONNECTION_NAME
    server_url = getattr(conn, "target", None) or os.environ.get("TAVILY_MCP_URL", "")
    logger.info(
        "Resolved Tavily connection %r -> id=%s url=%s",
        TAVILY_CONNECTION_NAME,
        conn_id,
        server_url,
    )
    return conn_id, server_url


def _build_definition(connection_id: str, server_url: str):
    """Build the PromptAgent definition with the Tavily MCP tool attached."""
    from azure.ai.projects.models import MCPTool, PromptAgentDefinition

    tavily_tool = MCPTool(
        server_label=MCP_SERVER_LABEL,
        server_url=server_url,
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
        connection_id, server_url = _resolve_tavily_connection(client)
        definition = _build_definition(connection_id, server_url)
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
