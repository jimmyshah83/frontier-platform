"""
MAF (Microsoft Agent Framework) implementation of the loan risk-assessment
workflow.

Mirrors the YAML workflow at `src/workflows/websearch-loan-workflow.yaml`,
but built with the canonical MAF API from the reference sample
``python/samples/03-workflows/agents/sequential_workflow_as_agent.py`` in
microsoft/agent-framework.

Key elements (matching the reference):
* ``FoundryChatClient`` — Azure AI Foundry chat client.
* ``Agent(client=..., instructions=..., name=...)`` — local agent definitions.
* ``WorkflowBuilder`` — explicit graph for parallel fan-out / fan-in.
* ``workflow.as_agent()`` — wraps the entire workflow as a single agent so
  it can be invoked as one participant by other coordinators or registered
  in Foundry.

Pipeline:

    dispatcher ─┬─► intake_agent  ──┐
                │                   ├─► aggregator ─► risk_agent ─► (output)
                └─► websearch_agent ┘
"""

from __future__ import annotations

import asyncio
import logging
import os
from dataclasses import dataclass
from typing import Any, AsyncIterator

from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Agent instructions — mirror the prompts from the YAML workflow.
# ---------------------------------------------------------------------------

INTAKE_INSTRUCTIONS = """\
You are a loan-application document processor.

Given a loan application document (URL or inline text), extract ALL
structured data into a single JSON object.

REQUIRED FIELDS:
- Applicant information (name, address, contact)
- Employment details (employer, income, years employed)
- Loan details (amount, purpose, term)
- Property information (type, address, value)
- Credit information (credit score, source)
- Assets and liabilities
- Monthly debt payments
- Declarations

CALCULATED METRICS:
- DTI Ratio  = (Monthly Debt Payments / (Annual Income / 12)) * 100
- LTV Ratio  = (Loan Amount / Property Value) * 100
- Reserves Months = Liquid Assets / Monthly Debt Payments

Return strict JSON only.
"""

WEB_SEARCH_INSTRUCTIONS = """\
You are a market-research assistant supporting loan risk assessment.
For every prompt, search for and concisely summarize:
1. Current 30-year fixed mortgage rates
2. Current US housing market trends in California (Oakland area)
3. Recent CFPB mortgage lending regulatory updates
4. Current economic indicators (unemployment rate, housing price index)

Cite sources where possible.
"""

RISK_INSTRUCTIONS = """\
You are a senior credit-risk officer. Given (a) extracted loan-application
data and (b) current market context, evaluate the application against
standard credit policies, identify similar historical cases, check
regulatory compliance, and produce a structured risk recommendation:
{ decision, confidence, key_drivers, mitigants, conditions }.
"""

WEB_SEARCH_PROMPT = """\
Search for the following current information to support loan risk assessment:
1. Current 30-year fixed mortgage rates
2. Current US housing market trends in California (Oakland area)
3. Recent CFPB mortgage lending regulatory updates
4. Current economic indicators (unemployment rate, housing price index)
"""

INTAKE_PROMPT_TEMPLATE = """\
Process the following loan application document and extract ALL structured data.

Document:
{document}
"""

RISK_PROMPT_TEMPLATE = """\
Perform a comprehensive risk assessment using the following data:

## Extracted Loan Application Data
{extracted}

## Current Market Context (from Web Search)
{market}

Evaluate this application against our credit policies, find similar
historical cases, check regulatory compliance, and provide a risk
recommendation.
"""


# ---------------------------------------------------------------------------
# Typed I/O
# ---------------------------------------------------------------------------


class RiskWorkflowInput(BaseModel):
    document_url: str | None = Field(default=None)
    document_text: str | None = Field(default=None)

    def render(self) -> str:
        if self.document_url:
            return f"Document URL: {self.document_url}"
        if self.document_text:
            return self.document_text
        raise ValueError("Either document_url or document_text must be provided.")


class RiskWorkflowResult(BaseModel):
    extracted_loan_data: str
    web_search_results: str
    risk_assessment: str


@dataclass
class StreamEvent:
    stage: str  # "intake" | "websearch" | "risk" | "final" | "workflow"
    status: str  # "started" | "completed" | "error"
    payload: Any | None = None

    def to_dict(self) -> dict[str, Any]:
        return {"stage": self.stage, "status": self.status, "payload": self.payload}


# ---------------------------------------------------------------------------
# Foundry client + agents
# ---------------------------------------------------------------------------


def _build_chat_client():
    """Build a FoundryChatClient from environment variables.

    Mirrors the reference sample's pattern:
        client = FoundryChatClient(
            project_endpoint=os.environ["FOUNDRY_PROJECT_ENDPOINT"],
            model=os.environ["FOUNDRY_MODEL"],
            credential=AzureCliCredential(),
        )
    """
    from agent_framework.foundry import FoundryChatClient  # type: ignore
    from azure.identity import AzureCliCredential  # type: ignore

    project_endpoint = (
        os.environ.get("FOUNDRY_PROJECT_ENDPOINT")
        or os.environ.get("AZURE_AI_PROJECT_ENDPOINT")
    )
    model = (
        os.environ.get("FOUNDRY_MODEL")
        or os.environ.get("AZURE_AI_MODEL_DEPLOYMENT")
    )
    if not project_endpoint:
        raise RuntimeError(
            "FOUNDRY_PROJECT_ENDPOINT (or AZURE_AI_PROJECT_ENDPOINT) is not set."
        )
    if not model:
        raise RuntimeError(
            "FOUNDRY_MODEL (or AZURE_AI_MODEL_DEPLOYMENT) is not set."
        )

    return FoundryChatClient(
        project_endpoint=project_endpoint,
        model=model,
        credential=AzureCliCredential(),
    )


def _build_agents(client) -> tuple[Any, Any, Any]:
    """Define the three local agents that mirror the YAML's hosted agents."""
    from agent_framework import Agent  # type: ignore

    intake = Agent(
        client=client,
        name=os.environ.get("INTAKE_AGENT_NAME", "loan-processing-json"),
        instructions=INTAKE_INSTRUCTIONS,
    )

    websearch_tools: list[Any] = []
    try:  # Hosted web-search tool ships with agent-framework when available.
        from agent_framework import HostedWebSearchTool  # type: ignore

        websearch_tools.append(HostedWebSearchTool())
    except Exception:  # pragma: no cover
        logger.info("HostedWebSearchTool not available; web-search agent runs unaugmented.")

    websearch = Agent(
        client=client,
        name=os.environ.get("WEB_SEARCH_AGENT_NAME", "web-search-agent"),
        instructions=WEB_SEARCH_INSTRUCTIONS,
        tools=websearch_tools or None,
    )

    risk = Agent(
        client=client,
        name=os.environ.get("RISK_AGENT_NAME", "risk-assessment-agent-aisearch-tool"),
        instructions=RISK_INSTRUCTIONS,
    )

    return intake, websearch, risk


# ---------------------------------------------------------------------------
# Workflow construction
# ---------------------------------------------------------------------------


def build_risk_workflow():
    """Build the MAF workflow.

    Returns the raw `Workflow` object — call `.run(input, stream=True)` for
    streaming, `.run(input)` for one-shot, or `.as_agent()` to wrap as an
    agent for re-use as a single participant elsewhere.
    """
    from agent_framework import (  # type: ignore
        Executor,
        WorkflowBuilder,
        WorkflowContext,
        handler,
    )

    client = _build_chat_client()
    intake_agent, websearch_agent, risk_agent = _build_agents(client)

    class Dispatcher(Executor):
        """Fans the workflow input out to intake + websearch in parallel."""

        @handler
        async def run(
            self,
            payload: RiskWorkflowInput | str,
            ctx: "WorkflowContext[str]",
        ) -> None:
            if isinstance(payload, str):
                payload = RiskWorkflowInput(document_text=payload)
            document = payload.render()
            await ctx.send_message(
                INTAKE_PROMPT_TEMPLATE.format(document=document),
                target_id="intake",
            )
            await ctx.send_message(WEB_SEARCH_PROMPT, target_id="websearch")

    class Aggregator(Executor):
        """Joins intake + websearch results, then dispatches to risk."""

        def __init__(self, executor_id: str = "aggregator"):
            super().__init__(id=executor_id)
            self._intake_text: str | None = None
            self._websearch_text: str | None = None

        @handler
        async def from_intake(self, msg: str, ctx: "WorkflowContext[str]") -> None:
            self._intake_text = msg
            await self._maybe_emit(ctx)

        @handler
        async def from_websearch(self, msg: str, ctx: "WorkflowContext[str]") -> None:
            self._websearch_text = msg
            await self._maybe_emit(ctx)

        async def _maybe_emit(self, ctx: "WorkflowContext[str]") -> None:
            if self._intake_text is None or self._websearch_text is None:
                return
            await ctx.send_message(
                RISK_PROMPT_TEMPLATE.format(
                    extracted=self._intake_text,
                    market=self._websearch_text,
                ),
                target_id="risk_finalizer",
            )

    class RiskFinalizer(Executor):
        """Calls the risk agent and yields the final structured result."""

        @handler
        async def run(self, msg: str, ctx: "WorkflowContext") -> None:
            response = await risk_agent.run(msg)
            text = getattr(response, "text", None) or str(response)
            await ctx.yield_output(text)

    # Lightweight passthroughs that call each agent and forward text to the
    # aggregator. Using `add_edge(agent, aggregator)` directly is also valid;
    # this version keeps message shapes uniform across both branches.
    class IntakeBranch(Executor):
        @handler
        async def run(self, msg: str, ctx: "WorkflowContext[str]") -> None:
            response = await intake_agent.run(msg)
            text = getattr(response, "text", None) or str(response)
            await ctx.send_message(
                text, target_id="aggregator", handler_name="from_intake"
            )

    class WebSearchBranch(Executor):
        @handler
        async def run(self, msg: str, ctx: "WorkflowContext[str]") -> None:
            response = await websearch_agent.run(msg)
            text = getattr(response, "text", None) or str(response)
            await ctx.send_message(
                text, target_id="aggregator", handler_name="from_websearch"
            )

    dispatcher = Dispatcher(id="dispatcher")
    intake_exec = IntakeBranch(id="intake")
    websearch_exec = WebSearchBranch(id="websearch")
    aggregator = Aggregator(id="aggregator")
    risk_finalizer = RiskFinalizer(id="risk_finalizer")

    workflow = (
        WorkflowBuilder(start_executor=dispatcher)
        .add_edge(dispatcher, intake_exec)
        .add_edge(dispatcher, websearch_exec)
        .add_edge(intake_exec, aggregator)
        .add_edge(websearch_exec, aggregator)
        .add_edge(aggregator, risk_finalizer)
        .build()
    )
    return workflow


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


async def run_risk_workflow(payload: RiskWorkflowInput) -> RiskWorkflowResult:
    """Run the workflow to completion and return the final result.

    Uses ``workflow.as_agent()`` — matching the reference sample's pattern —
    so the entire workflow is invoked as a single agent.
    """
    workflow = build_risk_workflow()
    agent = workflow.as_agent()
    response = await agent.run(payload.render())

    final_text = getattr(response, "text", None) or str(response)

    extracted = ""
    market = ""
    for msg in getattr(response, "messages", []) or []:
        author = getattr(msg, "author_name", "") or ""
        text = getattr(msg, "text", "") or ""
        if "loan-processing" in author or author.lower() == "intake":
            extracted = text
        elif "web-search" in author or author.lower() == "websearch":
            market = text

    return RiskWorkflowResult(
        extracted_loan_data=extracted,
        web_search_results=market,
        risk_assessment=final_text,
    )


async def stream_risk_workflow(
    payload: RiskWorkflowInput,
) -> AsyncIterator[StreamEvent]:
    """Stream stage-level events for the React UI (SSE-friendly)."""
    workflow = build_risk_workflow()
    yield StreamEvent("workflow", "started")

    try:
        events = workflow.run(payload, stream=True)
        async for event in events:
            mapped = _map_event(event)
            if mapped is not None:
                yield mapped
    except Exception as exc:  # pragma: no cover
        logger.exception("Workflow stream failed")
        yield StreamEvent("workflow", "error", payload={"message": str(exc)})
        return

    yield StreamEvent("workflow", "completed")


def _map_event(event: Any) -> StreamEvent | None:
    """Translate a workflow event into a UI-friendly StreamEvent."""
    executor_id = (
        getattr(event, "executor_id", None)
        or getattr(event, "source_id", None)
        or ""
    )
    data = getattr(event, "data", None)
    etype = getattr(event, "type", "")

    if etype == "output" and data is not None:
        text = getattr(data, "text", None) or str(data)
        return StreamEvent("final", "completed", payload={"text": text})

    if executor_id in {"intake", "websearch"}:
        text = getattr(data, "text", None) if data is not None else None
        return StreamEvent(
            executor_id,
            "completed" if etype.endswith("Completed") or etype == "output" else "started",
            payload={"text": text or (str(data) if data is not None else None)},
        )

    if executor_id == "risk_finalizer":
        text = getattr(data, "text", None) if data is not None else None
        return StreamEvent(
            "risk",
            "completed" if etype.endswith("Completed") else "started",
            payload={"text": text or (str(data) if data is not None else None)},
        )

    return None


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------


def _main() -> int:
    import argparse
    import json
    import sys

    try:
        from dotenv import load_dotenv  # type: ignore

        load_dotenv()
    except Exception:
        pass

    parser = argparse.ArgumentParser(description="Run the MAF risk-assessment workflow.")
    parser.add_argument("--document-url")
    parser.add_argument("--document-file")
    args = parser.parse_args()

    if not args.document_url and not args.document_file:
        parser.error("Provide --document-url or --document-file.")

    text = None
    if args.document_file:
        with open(args.document_file, encoding="utf-8") as f:
            text = f.read()

    payload = RiskWorkflowInput(document_url=args.document_url, document_text=text)
    result = asyncio.run(run_risk_workflow(payload))
    json.dump(result.model_dump(), sys.stdout, indent=2)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(_main())
