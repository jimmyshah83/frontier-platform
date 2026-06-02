"""
MAF (Microsoft Agent Framework) implementation of the loan risk-assessment
workflow.

Direct adaptation of the reference sample
``python/samples/03-workflows/agents/sequential_workflow_as_agent.py`` from
microsoft/agent-framework. The reference shows the canonical pattern:

    client = FoundryChatClient(...)
    writer   = Agent(client=client, instructions=..., name=...)
    reviewer = Agent(client=client, instructions=..., name=...)
    workflow = SequentialBuilder(participants=[writer, reviewer]).build()
    agent    = workflow.as_agent()
    response = await agent.run(prompt)

We use exactly the same shape with three agents:
``intake -> web_search -> risk``.

The previous YAML workflow runs the same three agents declaratively in
Foundry; this module is the code-first equivalent and is invoked through
the same ``Agent`` interface (so it can be re-used as a single
participant elsewhere or registered in Foundry).
"""

import asyncio
import logging
import os
from typing import Any

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

The previous message contains the extracted loan application data. Use
it as context, then summarize the following current market information
relevant to evaluating the application:

1. Current 30-year fixed mortgage rates
2. Current US housing market trends in California (Oakland area)
3. Recent CFPB mortgage lending regulatory updates
4. Current economic indicators (unemployment rate, housing price index)

Cite sources where possible.
"""

RISK_INSTRUCTIONS = """\
You are a senior credit-risk officer.

The conversation so far contains:
1. The extracted loan-application data (from the intake agent).
2. A market-context summary (from the web-search agent).

Evaluate the application against standard credit policies, identify
similar historical cases, check regulatory compliance, and produce a
structured risk recommendation:
{ decision, confidence, key_drivers, mitigants, conditions }.
"""


# ---------------------------------------------------------------------------
# Typed I/O for the FastAPI / React layer
# ---------------------------------------------------------------------------


class RiskWorkflowInput(BaseModel):
    document_url: str | None = Field(default=None)
    document_text: str | None = Field(default=None)

    def render(self) -> str:
        if self.document_url:
            return f"Process this loan application document: {self.document_url}"
        if self.document_text:
            return (
                "Process the following loan application document and extract "
                "ALL structured data:\n\n" + self.document_text
            )
        raise ValueError("Either document_url or document_text must be provided.")


class RiskWorkflowResult(BaseModel):
    extracted_loan_data: str
    web_search_results: str
    risk_assessment: str


class StreamEvent(BaseModel):
    stage: str  # "intake" | "websearch" | "risk" | "final" | "workflow"
    status: str  # "started" | "completed" | "error"
    payload: Any | None = None


# ---------------------------------------------------------------------------
# Workflow construction (matches the reference sample)
# ---------------------------------------------------------------------------


def _build_workflow():
    """Build the sequential workflow exactly like the reference sample."""
    from agent_framework import Agent  # type: ignore
    from agent_framework.foundry import FoundryChatClient  # type: ignore
    from agent_framework.orchestrations import SequentialBuilder  # type: ignore
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

    client = FoundryChatClient(
        project_endpoint=project_endpoint,
        model=model,
        credential=AzureCliCredential(),
    )

    intake = Agent(
        client=client,
        name=os.environ.get("INTAKE_AGENT_NAME", "loan-processing-json"),
        instructions=INTAKE_INSTRUCTIONS,
    )

    web_search_tools: list[Any] = []
    try:  # Hosted web-search tool ships with agent-framework when available.
        from agent_framework import HostedWebSearchTool  # type: ignore

        web_search_tools.append(HostedWebSearchTool())
    except Exception:  # pragma: no cover
        logger.info("HostedWebSearchTool not available; web-search agent runs unaugmented.")

    web_search = Agent(
        client=client,
        name=os.environ.get("WEB_SEARCH_AGENT_NAME", "web-search-agent"),
        instructions=WEB_SEARCH_INSTRUCTIONS,
        tools=web_search_tools or None,
    )

    risk = Agent(
        client=client,
        name=os.environ.get("RISK_AGENT_NAME", "risk-assessment-agent-aisearch-tool"),
        instructions=RISK_INSTRUCTIONS,
    )

    # ⬇️ Same call as the reference sample:
    # SequentialBuilder(participants=[writer, reviewer]).build()
    return SequentialBuilder(participants=[intake, web_search, risk]).build()


# Public alias kept for callers that imported the previous symbol.
build_risk_workflow = _build_workflow


# ---------------------------------------------------------------------------
# Public API used by the FastAPI server
# ---------------------------------------------------------------------------


async def run_risk_workflow(payload: RiskWorkflowInput) -> RiskWorkflowResult:
    """Run the sequential workflow as an agent and return aggregated output.

    Mirrors the reference sample:
        agent = workflow.as_agent()
        agent_response = await agent.run(prompt)
    """
    workflow = _build_workflow()
    agent = workflow.as_agent()
    response = await agent.run(payload.render())

    extracted = ""
    market = ""
    risk_text = getattr(response, "text", None) or str(response)

    for msg in getattr(response, "messages", []) or []:
        author = (getattr(msg, "author_name", "") or "").lower()
        text = getattr(msg, "text", "") or ""
        if "loan-processing" in author or "intake" in author:
            extracted = text
        elif "web-search" in author or "websearch" in author:
            market = text
        elif "risk" in author:
            risk_text = text

    return RiskWorkflowResult(
        extracted_loan_data=extracted,
        web_search_results=market,
        risk_assessment=risk_text,
    )


async def stream_risk_workflow(payload: RiskWorkflowInput):
    """Yield stage-level StreamEvents for the React UI (SSE-friendly).

    Uses ``workflow.run(prompt, stream=True)`` — the same pattern as the
    ``azure_ai_agents_streaming.py`` sample — which surfaces every agent's
    streaming updates with ``author_name`` set, so the UI can attribute
    each chunk to the correct stage (intake / websearch / risk).
    """
    yield StreamEvent(stage="workflow", status="started")

    try:
        from agent_framework import AgentRunUpdateEvent  # type: ignore
    except ImportError:  # older naming
        AgentRunUpdateEvent = None  # type: ignore

    try:
        workflow = _build_workflow()
    except Exception as exc:
        logger.exception("Failed to build workflow")
        yield StreamEvent(
            stage="workflow", status="error", payload={"message": str(exc)}
        )
        return

    last_stage: str | None = None
    buffer: dict[str, list[str]] = {"intake": [], "websearch": [], "risk": []}

    try:
        events = workflow.run(payload.render(), stream=True)
        async for event in events:
            update = getattr(event, "data", event)
            author = (
                getattr(update, "author_name", None)
                or getattr(update, "role", None)
                or ""
            )
            text = getattr(update, "text", "") or ""
            stage = _stage_for(author)
            if stage is None:
                continue

            if stage != last_stage:
                if last_stage and buffer[last_stage]:
                    yield StreamEvent(
                        stage=last_stage,
                        status="completed",
                        payload={"text": "".join(buffer[last_stage])},
                    )
                yield StreamEvent(stage=stage, status="started")
                last_stage = stage

            if text:
                buffer[stage].append(text)
                # Incremental delta so the UI fills in live.
                yield StreamEvent(
                    stage=stage, status="running", payload={"text": text}
                )

        if last_stage and buffer[last_stage]:
            yield StreamEvent(
                stage=last_stage,
                status="completed",
                payload={"text": "".join(buffer[last_stage])},
            )

        yield StreamEvent(
            stage="final",
            status="completed",
            payload={
                "extracted_loan_data": "".join(buffer["intake"]),
                "web_search_results": "".join(buffer["websearch"]),
                "risk_assessment": "".join(buffer["risk"]),
            },
        )
        yield StreamEvent(stage="workflow", status="completed")

    except Exception as exc:
        logger.exception("Workflow stream failed")
        yield StreamEvent(
            stage="workflow", status="error", payload={"message": str(exc)}
        )


def _stage_for(author: str) -> str | None:
    """Map an agent author name to a UI stage key."""
    a = (author or "").lower()
    if "loan-processing" in a or "intake" in a:
        return "intake"
    if "web-search" in a or "websearch" in a:
        return "websearch"
    if "risk" in a:
        return "risk"
    return None


# ---------------------------------------------------------------------------
# CLI entry point — same flow as the reference sample's `main()`
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
