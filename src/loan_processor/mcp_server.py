"""
Content Understanding MCP Server

This module implements a local MCP server that exposes Content Understanding
as MCP tools for loan document processing. Can be run locally for testing
or deployed to Azure Container Apps.
"""

import asyncio
import json
import logging
import os
from dataclasses import dataclass
from typing import Any

import httpx
from azure.identity import DefaultAzureCredential
from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import Tool, TextContent
from pydantic import BaseModel, Field

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


# ============================================================================
# Loan Application Schema
# ============================================================================

class LoanApplicationData(BaseModel):
    """Extracted loan application data."""

    applicant_name: str | None = Field(default=None, description="Full name of the loan applicant")
    ssn_last_4: str | None = Field(default=None, description="Last 4 digits of SSN")
    annual_income: float | None = Field(default=None, description="Annual income in USD")
    employment_status: str | None = Field(default=None, description="Employment status (employed, self-employed, unemployed)")
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

    async def _get_token(self) -> str:
        """Get access token for Content Understanding API."""
        token = self.credential.get_token("https://cognitiveservices.azure.com/.default")
        return token.token

    async def _poll_for_result(self, client: httpx.AsyncClient, operation_location: str, token: str) -> dict[str, Any]:
        """Poll for analysis results."""
        logger.info(f"Polling for results at: {operation_location}")
        for _ in range(60):  # Max 60 attempts (2 minutes)
            await asyncio.sleep(2)

            result_response = await client.get(
                operation_location,
                headers={"Authorization": f"Bearer {token}"},
            )
            result_response.raise_for_status()
            result = result_response.json()

            status = result.get("status", "")
            if status == "Succeeded":
                logger.info("Document analysis completed successfully")
                return result
            elif status in ("Failed", "Canceled"):
                raise ValueError(f"Analysis failed with status: {status}")

            logger.debug(f"Analysis status: {status}, waiting...")

        raise TimeoutError("Document analysis timed out")

    async def analyze_document(self, document_url: str) -> dict[str, Any]:
        """
        Analyze a document using Content Understanding via URL.

        Args:
            document_url: URL of the document to analyze (public URL, raw GitHub URL, etc.)

        Returns:
            Analysis result with extracted fields
        """
        token = await self._get_token()

        # Remove trailing slash from endpoint if present
        endpoint = self.endpoint.rstrip("/")
        analyzer_id = "prebuilt-document"
        analyze_url = f"{endpoint}/contentunderstanding/analyzers/{analyzer_id}:analyze"

        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        }

        params = {"api-version": self.api_version}
        body = {"inputs": [{"url": document_url}]}

        async with httpx.AsyncClient(timeout=120.0) as client:
            logger.info(f"Starting document analysis for URL: {document_url}")
            logger.debug(f"Analyze URL: {analyze_url}")
            response = await client.post(
                analyze_url,
                headers=headers,
                params=params,
                json=body,
            )
            
            # Log error details if request fails
            if response.status_code >= 400:
                logger.error(f"API Error: {response.status_code} - {response.text}")
            
            response.raise_for_status()

            operation_location = response.headers.get("Operation-Location")
            if not operation_location:
                raise ValueError("No Operation-Location header in response")

            return await self._poll_for_result(client, operation_location, token)


# ============================================================================
# Field Extraction Logic
# ============================================================================

def extract_loan_fields(analysis_result: dict[str, Any]) -> LoanApplicationData:
    """
    Extract loan application fields from Content Understanding result.

    This function parses the analysis result and extracts relevant loan fields.
    Since we're using the prebuilt-document analyzer, we need to search for
    fields in the markdown content and key-value pairs.
    """
    contents = analysis_result.get("result", {}).get("contents", [])

    if not contents:
        return LoanApplicationData()

    content = contents[0]
    markdown = content.get("markdown", "")
    fields = content.get("fields", {})
    kv_pairs = content.get("keyValuePairs", [])

    # Build a lookup from key-value pairs
    kv_lookup: dict[str, str] = {}
    for kv in kv_pairs:
        key = kv.get("key", {}).get("content", "").lower().strip()
        value = kv.get("value", {}).get("content", "")
        if key and value:
            kv_lookup[key] = value

    # Extract fields using various strategies
    extracted = LoanApplicationData(raw_markdown=markdown[:2000] if markdown else None)

    # Try to find applicant name
    for key in ["applicant name", "borrower name", "name", "full name", "applicant"]:
        if key in kv_lookup:
            extracted.applicant_name = kv_lookup[key]
            break

    # Try to find SSN (last 4)
    for key in ["ssn", "social security", "social security number", "ssn (last 4)"]:
        if key in kv_lookup:
            ssn_value = kv_lookup[key]
            # Extract last 4 digits
            digits = "".join(filter(str.isdigit, ssn_value))
            if len(digits) >= 4:
                extracted.ssn_last_4 = digits[-4:]
            break

    # Try to find annual income
    for key in ["annual income", "yearly income", "income", "gross income", "annual salary"]:
        if key in kv_lookup:
            income_str = kv_lookup[key].replace(",", "").replace("$", "")
            try:
                extracted.annual_income = float(income_str)
            except ValueError:
                pass
            break

    # Try to find employment status
    for key in ["employment status", "employment", "work status"]:
        if key in kv_lookup:
            extracted.employment_status = kv_lookup[key]
            break

    # Try to find employer name
    for key in ["employer", "employer name", "company", "current employer"]:
        if key in kv_lookup:
            extracted.employer_name = kv_lookup[key]
            break

    # Try to find loan amount
    for key in ["loan amount", "amount requested", "requested amount", "loan amount requested"]:
        if key in kv_lookup:
            amount_str = kv_lookup[key].replace(",", "").replace("$", "")
            try:
                extracted.loan_amount_requested = float(amount_str)
            except ValueError:
                pass
            break

    # Try to find loan purpose
    for key in ["loan purpose", "purpose", "purpose of loan", "loan type"]:
        if key in kv_lookup:
            extracted.loan_purpose = kv_lookup[key]
            break

    # Try to find property address
    for key in ["property address", "address", "property", "subject property"]:
        if key in kv_lookup:
            extracted.property_address = kv_lookup[key]
            break

    # Calculate confidence score (average of available confidences)
    confidences = []
    for field_data in fields.values():
        if isinstance(field_data, dict) and "confidence" in field_data:
            confidences.append(field_data["confidence"])

    if confidences:
        extracted.confidence_score = sum(confidences) / len(confidences)

    return extracted


# ============================================================================
# MCP Server
# ============================================================================

def create_mcp_server() -> Server:
    """Create and configure the MCP server with Content Understanding tools."""

    server = Server("content-understanding-mcp")

    # Get configuration from environment
    endpoint = os.getenv("AZURE_AI_SERVICES_ENDPOINT")
    if not endpoint:
        logger.warning("AZURE_AI_SERVICES_ENDPOINT not set - using placeholder")
        endpoint = "https://placeholder.cognitiveservices.azure.com"

    credential = DefaultAzureCredential()
    cu_client = ContentUnderstandingClient(endpoint=endpoint, credential=credential)

    @server.list_tools()
    async def list_tools() -> list[Tool]:
        """List available MCP tools."""
        return [
            Tool(
                name="extract_loan_data",
                description="""Extract structured loan application data from a document URL.

Extracts the following fields from loan application documents:
- Applicant name
- SSN (last 4 digits only)
- Annual income
- Employment status
- Employer name
- Loan amount requested
- Loan purpose
- Property address

Supports PDF, images, and Office documents.
Provide a publicly accessible URL (e.g., raw GitHub URL, public blob URL).""",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "document_url": {
                            "type": "string",
                            "description": "Public URL of the loan document to analyze (e.g., https://raw.githubusercontent.com/user/repo/main/doc.pdf)",
                        },
                    },
                    "required": ["document_url"],
                },
            ),
            Tool(
                name="get_document_text",
                description="""Extract full text/markdown content from a document URL.

Returns the complete text content of a document in markdown format,
useful for further analysis or summarization.
Provide a publicly accessible URL.""",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "document_url": {
                            "type": "string",
                            "description": "Public URL of the document to extract text from",
                        },
                    },
                    "required": ["document_url"],
                },
            ),
        ]

    @server.call_tool()
    async def call_tool(name: str, arguments: dict[str, Any]) -> list[TextContent]:
        """Handle tool invocations."""

        if name == "extract_loan_data":
            document_url = arguments.get("document_url")

            if not document_url:
                return [TextContent(type="text", text="Error: document_url is required")]

            try:
                logger.info(f"Extracting loan data from URL: {document_url}")
                result = await cu_client.analyze_document(document_url)
                loan_data = extract_loan_fields(result)

                # Return as formatted JSON
                return [
                    TextContent(
                        type="text",
                        text=json.dumps(loan_data.model_dump(exclude_none=True), indent=2),
                    )
                ]
            except Exception as e:
                logger.error(f"Error extracting loan data: {e}")
                return [TextContent(type="text", text=f"Error: {str(e)}")]

        elif name == "get_document_text":
            document_url = arguments.get("document_url")

            if not document_url:
                return [TextContent(type="text", text="Error: document_url is required")]

            try:
                logger.info(f"Extracting text from URL: {document_url}")
                result = await cu_client.analyze_document(document_url)
                contents = result.get("result", {}).get("contents", [])

                if contents:
                    markdown = contents[0].get("markdown", "")
                    return [TextContent(type="text", text=markdown)]
                else:
                    return [TextContent(type="text", text="No content extracted from document")]

            except Exception as e:
                logger.error(f"Error extracting document text: {e}")
                return [TextContent(type="text", text=f"Error: {str(e)}")]

        else:
            return [TextContent(type="text", text=f"Unknown tool: {name}")]

    return server


async def main():
    """Run the MCP server using stdio transport."""
    from dotenv import load_dotenv

    load_dotenv()

    logger.info("Starting Content Understanding MCP Server...")
    server = create_mcp_server()

    async with stdio_server() as (read_stream, write_stream):
        await server.run(
            read_stream,
            write_stream,
            server.create_initialization_options(),
        )


if __name__ == "__main__":
    asyncio.run(main())
