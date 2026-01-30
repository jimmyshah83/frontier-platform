# Copyright (c) Microsoft. All rights reserved.
"""Configuration settings for the Loan Processing System."""

import os
from dataclasses import dataclass


@dataclass
class AzureConfig:
    """Azure service configuration."""

    # Azure AI Foundry
    azure_ai_project_endpoint: str
    azure_ai_model_deployment: str

    # Azure Storage
    storage_account_name: str
    storage_container_name: str

    # Content Understanding MCP Server
    content_understanding_mcp_url: str

    @classmethod
    def from_env(cls) -> "AzureConfig":
        """Load configuration from environment variables."""
        return cls(
            azure_ai_project_endpoint=os.environ.get(
                "AZURE_AI_PROJECT_ENDPOINT", ""
            ),
            azure_ai_model_deployment=os.environ.get(
                "AZURE_AI_MODEL_DEPLOYMENT", "gpt-4o"
            ),
            storage_account_name=os.environ.get(
                "AZURE_STORAGE_ACCOUNT_NAME", ""
            ),
            storage_container_name=os.environ.get(
                "AZURE_STORAGE_CONTAINER_NAME", "loan-documents"
            ),
            content_understanding_mcp_url=os.environ.get(
                "CONTENT_UNDERSTANDING_MCP_URL", ""
            ),
        )

    def validate(self) -> list[str]:
        """Validate that required configuration is set.

        Returns:
            List of missing configuration items.
        """
        missing = []
        if not self.azure_ai_project_endpoint:
            missing.append("AZURE_AI_PROJECT_ENDPOINT")
        if not self.storage_account_name:
            missing.append("AZURE_STORAGE_ACCOUNT_NAME")
        return missing
