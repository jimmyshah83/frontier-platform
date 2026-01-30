#!/usr/bin/env python3
"""
Health check for Loan Processor PoC.
Validates that all dependencies are installed and Azure connectivity works.
"""

import sys
from pathlib import Path


def print_status(message: str, success: bool) -> bool:
    """Print status with indicator."""
    status = "✓" if success else "✗"
    color = "\033[92m" if success else "\033[91m"
    reset = "\033[0m"
    print(f"  {color}{status}{reset} {message}")
    return success


def check_core_packages() -> bool:
    """Check core Python packages."""
    print("\n📦 Core Packages:")
    all_ok = True

    packages = [
        ("pydantic", "Pydantic"),
        ("dotenv", "python-dotenv"),
        ("azure.identity", "Azure Identity"),
        ("azure.storage.blob", "Azure Storage Blob"),
    ]

    for module, name in packages:
        try:
            __import__(module)
            print_status(name, True)
        except ImportError as e:
            print_status(f"{name}: {e}", False)
            all_ok = False

    return all_ok


def check_agent_framework() -> bool:
    """Check agent-framework packages."""
    print("\n🤖 Agent Framework:")
    all_ok = True

    try:
        from agent_framework import ChatAgent
        print_status("agent-framework", True)
    except ImportError as e:
        print_status(f"agent-framework: {e}", False)
        all_ok = False

    try:
        from agent_framework_azure_ai import AzureAIAgentClient
        print_status("agent-framework-azure-ai", True)
    except ImportError as e:
        print_status(f"agent-framework-azure-ai: {e}", False)
        all_ok = False

    return all_ok


def check_mcp() -> bool:
    """Check MCP SDK."""
    print("\n🔌 MCP SDK:")

    try:
        from mcp.server import Server
        print_status("mcp[cli]", True)
        return True
    except ImportError as e:
        print_status(f"mcp: {e}", False)
        return False


def check_config() -> bool:
    """Check local config module."""
    print("\n⚙️  Configuration:")

    try:
        from loan_processor.config import AzureConfig
        print_status("AzureConfig loads", True)
        return True
    except ImportError as e:
        print_status(f"Config import failed: {e}", False)
        return False


def check_azure_connectivity() -> bool:
    """Check Azure connectivity (optional - requires .env)."""
    print("\n☁️  Azure Connectivity:")

    try:
        from dotenv import load_dotenv
        import os

        load_dotenv()

        storage_account = os.getenv("AZURE_STORAGE_ACCOUNT_NAME")
        if not storage_account:
            print_status("AZURE_STORAGE_ACCOUNT_NAME not set (skipping)", True)
            return True

        from azure.identity import DefaultAzureCredential
        from azure.storage.blob import BlobServiceClient

        credential = DefaultAzureCredential()
        blob_url = f"https://{storage_account}.blob.core.windows.net"
        client = BlobServiceClient(blob_url, credential=credential)

        # Try to list containers (validates connectivity)
        containers = list(client.list_containers(max_results=1))
        print_status(f"Connected to {storage_account}", True)
        return True

    except Exception as e:
        print_status(f"Azure connection failed: {e}", False)
        print("    (This is OK if you haven't deployed Azure resources yet)")
        return True  # Don't fail health check for this


def main() -> int:
    """Run health checks."""
    print("=" * 50)
    print("🏦 Loan Processor PoC - Health Check")
    print("=" * 50)

    results = [
        check_core_packages(),
        check_agent_framework(),
        check_mcp(),
        check_config(),
        check_azure_connectivity(),
    ]

    print("\n" + "=" * 50)
    if all(results):
        print("✅ All checks passed!")
        print("\nNext: Create .env from .env.example and configure Azure")
        return 0
    else:
        print("❌ Some checks failed")
        return 1


if __name__ == "__main__":
    sys.exit(main())
