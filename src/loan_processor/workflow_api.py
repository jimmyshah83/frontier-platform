"""
FastAPI server exposing the MAF risk-assessment workflow over HTTP/SSE.

Endpoints
---------
GET  /health                  -> liveness probe
POST /workflows/risk/run      -> run to completion, return final JSON
POST /workflows/risk/stream   -> Server-Sent Events stream of stage updates

Run locally:
    uv run uvicorn loan_processor.workflow_api:app \\
        --host $WORKFLOW_API_HOST --port $WORKFLOW_API_PORT --reload
"""

from __future__ import annotations

import json
import logging
import os
from typing import AsyncIterator

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from sse_starlette.sse import EventSourceResponse

from .workflows import (
    RiskWorkflowInput,
    RiskWorkflowResult,
    run_risk_workflow,
    stream_risk_workflow,
)

logger = logging.getLogger(__name__)


def _setup_observability() -> None:
    """Wire OpenTelemetry → Application Insights so traces flow into Foundry."""
    conn = os.environ.get("APPLICATIONINSIGHTS_CONNECTION_STRING")
    if not conn:
        logger.info("APPLICATIONINSIGHTS_CONNECTION_STRING not set; skipping telemetry.")
        return
    try:
        from azure.monitor.opentelemetry import configure_azure_monitor  # type: ignore

        configure_azure_monitor(connection_string=conn)
        logger.info("Azure Monitor telemetry enabled.")
    except Exception:  # pragma: no cover - optional dependency
        logger.exception("Failed to configure Azure Monitor; continuing without telemetry.")


_setup_observability()

app = FastAPI(
    title="MAF Risk Assessment Workflow",
    version="1.0.0",
    description=(
        "Microsoft Agent Framework workflow orchestrating the existing "
        "loan-processing-json, web-search-agent, and "
        "risk-assessment-agent-aisearch-tool Foundry agents."
    ),
)

origins = [
    o.strip()
    for o in os.environ.get(
        "WORKFLOW_API_CORS_ORIGINS",
        "http://localhost:5173,http://127.0.0.1:5173",
    ).split(",")
    if o.strip()
]
app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "healthy", "service": "maf-risk-workflow"}


@app.post("/workflows/risk/run", response_model=RiskWorkflowResult)
async def run_workflow(payload: RiskWorkflowInput) -> RiskWorkflowResult:
    if not payload.document_url and not payload.document_text:
        raise HTTPException(
            status_code=400,
            detail="document_url or document_text is required.",
        )
    try:
        return await run_risk_workflow(payload)
    except Exception as exc:
        logger.exception("Workflow run failed")
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@app.post("/workflows/risk/stream")
async def stream_workflow(payload: RiskWorkflowInput):
    if not payload.document_url and not payload.document_text:
        raise HTTPException(
            status_code=400,
            detail="document_url or document_text is required.",
        )

    async def event_source() -> AsyncIterator[dict]:
        async for event in stream_risk_workflow(payload):
            yield {
                "event": event.stage,
                "data": json.dumps(event.to_dict()),
            }

    return EventSourceResponse(event_source())
