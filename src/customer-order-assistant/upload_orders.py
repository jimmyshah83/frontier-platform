"""Upload sample orders to Azure Cosmos DB."""

import json
import os
import sys
from pathlib import Path

from dotenv import load_dotenv
from azure.cosmos import CosmosClient, exceptions
from azure.identity import DefaultAzureCredential

# Load .env from project root
load_dotenv(Path(__file__).resolve().parent.parent.parent / ".env")

# --- Configuration ---
COSMOS_ENDPOINT = os.environ.get("COSMOS_ENDPOINT", "")
DATABASE_NAME = os.environ.get("COSMOS_DATABASE", "frontier-platform")
CONTAINER_NAME = os.environ.get("COSMOS_CONTAINER", "orders")


def main():
    if not COSMOS_ENDPOINT:
        print("Error: Set COSMOS_ENDPOINT in .env file at the project root.")
        print("  COSMOS_ENDPOINT=https://<your-account>.documents.azure.com:443/")
        sys.exit(1)

    # Load sample data
    script_dir = os.path.dirname(os.path.abspath(__file__))
    data_file = os.path.join(script_dir, "sample_orders.json")

    with open(data_file, "r") as f:
        orders = json.load(f)

    print(f"Loaded {len(orders)} orders from sample_orders.json")

    # Connect using Entra ID (DefaultAzureCredential)
    print(f"Connecting to {COSMOS_ENDPOINT} ...")
    credential = DefaultAzureCredential()
    client = CosmosClient(COSMOS_ENDPOINT, credential=credential)

    database = client.get_database_client(DATABASE_NAME)
    container = database.get_container_client(CONTAINER_NAME)

    # Upsert each order
    success = 0
    failed = 0
    for order in orders:
        try:
            container.upsert_item(order)
            print(f"  ✓ {order['id']} — {order['customerName']} ({order['status']})")
            success += 1
        except exceptions.CosmosHttpResponseError as e:
            print(f"  ✗ {order['id']}: {e.message}")
            failed += 1

    print(f"\nDone: {success} uploaded, {failed} failed.")


if __name__ == "__main__":
    main()
