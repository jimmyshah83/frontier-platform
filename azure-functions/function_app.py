"""
Azure Functions HTTP-based MCP Server for Content Understanding

Exposes MCP tools via HTTP endpoints compatible with Azure Functions.
"""

import asyncio
import json
import logging
import os
from dataclasses import dataclass
from typing import Any

import azure.functions as func
import httpx
from azure.identity import DefaultAzureCredential
from pydantic import BaseModel, Field

app = func.FunctionApp(http_auth_level=func.AuthLevel.FUNCTION)
logger = logging.getLogger(__name__)


# ============================================================================
# Loan Application Schema
# ============================================================================

class LoanApplicationData(BaseModel):
    """Extracted loan application data."""

    applicant_name: str | None = Field(default=None, description="Full name of the loan applicant")
    ssn_last_4: str | None = Field(default=None, description="Last 4 digits of SSN")
    annual_income: float | None = Field(default=None, description="Annual income in USD")
    employment_status: str | None = Field(default=None, description="Employment status")
    employer_name: str | None = Field(default=None, description="Name of current employer")
    loan_amount_requested: float | None = Field(default=None, description="Requested loan amount in USD")
    loan_purpose: str | None = Field(default=None, description="Purpose of the loan")
    property_address: str | None = Field(default=None, description="Property address for the loan")
    confidence_score: float | None = Field(default=None, description="Overall extraction confidence")
    raw_markdown: str | None = Field(default=None, description="Raw markdown content from document")


# ============================================================================
# Content Understanding Client
# ============================================================================

@dataclass
class ContentUnderstandingClient:
    """Client for Azure Content Understanding API."""

    endpoint: str
    credential: DefaultAzureCredential
    api_version: str = "2025-11-01"

    def _get_token(self) -> str:
        """Get access token for Content Understanding API."""
        token = self.credential.get_token("https://cognitiveservices.azure.com/.default")
        return token.token

    async def analyze_document(self, document_url: str) -> dict[str, Any]:
        """Analyze a document using Content Understanding."""
        token = self._get_token()

        analyzer_id = "prebuilt-document"
        analyze_url = f"{self.endpoint}/contentunderstanding/analyzers/{analyzer_id}:analyze"

        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        }

        params = {"api-version": self.api_version}
        body = {"inputs": [{"url": document_url}]}

        async with httpx.AsyncClient(timeout=120.0) as client:
            logger.info(f"Starting document analysis for: {document_url}")
            response = await client.post(
                analyze_url,
                headers=headers,
                params=params,
                json=body,
            )
            response.raise_for_status()

            operation_location = response.headers.get("Operation-Location")
            if not operation_location:
                raise ValueError("No Operation-Location header in response")

            # Poll for results
            for _ in range(60):
                await asyncio.sleep(2)
                result_response = await client.get(
                    operation_location,
                    headers={"Authorization": f"Bearer {token}"},
                )
                result_response.raise_for_status()
                result = result_response.json()

                status = result.get("status", "")
                if status == "Succeeded":
                    return result
                elif status in ("Failed", "Canceled"):
                    raise ValueError(f"Analysis failed with status: {status}")

            raise TimeoutError("Document analysis timed out")


# ============================================================================
# Field Extraction Logic
# ============================================================================

def extract_loan_fields(analysis_result: dict[str, Any]) -> LoanApplicationData:
    """Extract loan application fields from Content Understanding result."""
    contents = analysis_result.get("result", {}).get("contents", [])

    if not contents:
        return LoanApplicationData()

    content = contents[0]
    markdown = content.get("markdown", "")
    fields = content.get("fields", {})
    kv_pairs = content.get("keyValuePairs", [])

    kv_lookup: dict[str, str] = {}
    for kv in kv_pairs:
        key = kv.get("key", {}).get("content", "").lower().strip()
        value = kv.get("value", {}).get("content", "")
        if key and value:
            kv_lookup[key] = value

    extracted = LoanApplicationData(raw_markdown=markdown[:2000] if markdown else None)

    # Extract fields
    for key in ["applicant name", "borrower name", "name", "full name"]:
        if key in kv_lookup:
            extracted.applicant_name = kv_lookup[key]
            break

    for key in ["ssn", "social security", "ssn (last 4)"]:
        if key in kv_lookup:
            digits = "".join(filter(str.isdigit, kv_lookup[key]))
            if len(digits) >= 4:
                extracted.ssn_last_4 = digits[-4:]
            break

    for key in ["annual income", "yearly income", "income", "gross income"]:
        if key in kv_lookup:
            try:
                extracted.annual_income = float(kv_lookup[key].replace(",", "").replace("$", ""))
            except ValueError:
                pass
            break

    for key in ["employment status", "employment"]:
        if key in kv_lookup:
            extracted.employment_status = kv_lookup[key]
            break

    for key in ["employer", "employer name", "current employer"]:
        if key in kv_lookup:
            extracted.employer_name = kv_lookup[key]
            break

    for key in ["loan amount", "amount requested", "loan amount requested"]:
        if key in kv_lookup:
            try:
                extracted.loan_amount_requested = float(kv_lookup[key].replace(",", "").replace("$", ""))
            except ValueError:
                pass
            break

    for key in ["loan purpose", "purpose"]:
        if key in kv_lookup:
            extracted.loan_purpose = kv_lookup[key]
            break

    for key in ["property address", "address", "property"]:
        if key in kv_lookup:
            extracted.property_address = kv_lookup[key]
            break

    confidences = [f["confidence"] for f in fields.values() if isinstance(f, dict) and "confidence" in f]
    if confidences:
        extracted.confidence_score = sum(confidences) / len(confidences)

    return extracted


# ============================================================================
# Singleton client
# ============================================================================

_cu_client: ContentUnderstandingClient | None = None


def get_cu_client() -> ContentUnderstandingClient:
    """Get or create Content Understanding client."""
    global _cu_client
    if _cu_client is None:
        endpoint = os.getenv("AZURE_AI_SERVICES_ENDPOINT")
        if not endpoint:
            raise ValueError("AZURE_AI_SERVICES_ENDPOINT is required")
        _cu_client = ContentUnderstandingClient(
            endpoint=endpoint,
            credential=DefaultAzureCredential()
        )
    return _cu_client


# ============================================================================
# HTTP Endpoints
# ============================================================================

@app.route(route="health", methods=["GET"])
async def health_check(req: func.HttpRequest) -> func.HttpResponse:
    """Health check endpoint."""
    return func.HttpResponse(
        json.dumps({
            "status": "healthy",
            "service": "content-understanding-mcp",
            "version": "1.0.0"
        }),
        mimetype="application/json"
    )


@app.route(route="mcp/tools", methods=["GET"])
async def list_tools(req: func.HttpRequest) -> func.HttpResponse:
    """List available MCP tools."""
    tools = [
        {
            "name": "extract_loan_data",
            "description": "Extract structured loan application data from a document",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "document_url": {
                        "type": "string",
                        "description": "URL of the loan document to analyze",
                    },
                },
                "required": ["document_url"],
            },
        },
        {
            "name": "get_document_text",
            "description": "Extract full text/markdown content from a document",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "document_url": {
                        "type": "string",
                        "description": "URL of the document",
                    },
                },
                "required": ["document_url"],
            },
        },
    ]
    return func.HttpResponse(
        json.dumps({"tools": tools}),
        mimetype="application/json"
    )


@app.route(route="mcp/tools/call", methods=["POST"])
async def call_tool(req: func.HttpRequest) -> func.HttpResponse:
    """Invoke an MCP tool."""
    try:
        body = req.get_json()
        tool_name = body.get("name")
        arguments = body.get("arguments", {})

        if tool_name == "extract_loan_data":
            document_url = arguments.get("document_url")
            if not document_url:
                return func.HttpResponse(
                    json.dumps({"error": "document_url is required"}),
                    status_code=400,
                    mimetype="application/json"
                )

            client = get_cu_client()
            result = await client.analyze_document(document_url)
            loan_data = extract_loan_fields(result)

            return func.HttpResponse(
                json.dumps({
                    "content": [
                        {"type": "text", "text": json.dumps(loan_data.model_dump(exclude_none=True), indent=2)}
                    ]
                }),
                mimetype="application/json"
            )

        elif tool_name == "get_document_text":
            document_url = arguments.get("document_url")
            if not document_url:
                return func.HttpResponse(
                    json.dumps({"error": "document_url is required"}),
                    status_code=400,
                    mimetype="application/json"
                )

            client = get_cu_client()
            result = await client.analyze_document(document_url)
            contents = result.get("result", {}).get("contents", [])
            markdown = contents[0].get("markdown", "") if contents else ""

            return func.HttpResponse(
                json.dumps({
                    "content": [{"type": "text", "text": markdown}]
                }),
                mimetype="application/json"
            )

        else:
            return func.HttpResponse(
                json.dumps({"error": f"Unknown tool: {tool_name}"}),
                status_code=400,
                mimetype="application/json"
            )

    except Exception as e:
        logger.exception("Error calling tool")
        return func.HttpResponse(
            json.dumps({"error": str(e)}),
            status_code=500,
            mimetype="application/json"
        )
