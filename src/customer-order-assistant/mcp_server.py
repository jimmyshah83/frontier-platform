"""
Customer Order Assistant — Cosmos DB MCP Server

Exposes order CRUD operations as MCP tools via HTTP Streamable transport.
Authentication: Key-based (Azure Functions function key when deployed).
"""

import json
import logging
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path

from dotenv import load_dotenv
from mcp.server.fastmcp import FastMCP
from azure.cosmos.aio import CosmosClient
from azure.identity.aio import DefaultAzureCredential

# Load .env from project root (for local development)
_env_path = Path(__file__).resolve().parent.parent.parent / ".env"
if _env_path.exists():
    load_dotenv(_env_path)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# --- Configuration ---
COSMOS_ENDPOINT = os.environ.get("COSMOS_ENDPOINT", "")
COSMOS_KEY = os.environ.get("COSMOS_KEY", "")
COSMOS_DATABASE = os.environ.get("COSMOS_DATABASE", "frontier-db")
COSMOS_CONTAINER = os.environ.get("COSMOS_CONTAINER", "orders")

# --- MCP Server ---
mcp = FastMCP(
    "Customer Order Assistant",
    instructions=(
        "You help users manage customer orders stored in Azure Cosmos DB. "
        "Use the available tools to query, create, update, and cancel orders."
    ),
)

# --- Lazy Cosmos DB connection ---
_credential = None
_client: CosmosClient | None = None
_container = None


async def get_container():
    """Get (or create) the Cosmos DB container client."""
    global _credential, _client, _container
    if _container is None:
        if COSMOS_KEY:
            logger.info("Connecting to Cosmos DB with account key")
            _client = CosmosClient(COSMOS_ENDPOINT, credential=COSMOS_KEY)
        else:
            logger.info("Connecting to Cosmos DB with DefaultAzureCredential")
            _credential = DefaultAzureCredential()
            _client = CosmosClient(COSMOS_ENDPOINT, credential=_credential)

        db = _client.get_database_client(COSMOS_DATABASE)
        _container = db.get_container_client(COSMOS_CONTAINER)
    return _container


def _strip_cosmos_metadata(item: dict) -> dict:
    """Remove internal Cosmos DB fields from an item."""
    for key in ("_rid", "_self", "_etag", "_attachments", "_ts"):
        item.pop(key, None)
    return item


# ============================================================================
# MCP Tools — Read
# ============================================================================


@mcp.tool()
async def get_order(order_id: str, customer_id: str) -> str:
    """Get a specific order by its order ID and customer ID.

    Args:
        order_id: The order ID (e.g. "order-1001")
        customer_id: The customer ID / partition key (e.g. "contoso-001")
    """
    container = await get_container()
    try:
        item = await container.read_item(item=order_id, partition_key=customer_id)
        return json.dumps(_strip_cosmos_metadata(item), indent=2, default=str)
    except Exception as e:
        return json.dumps({"error": str(e)})


@mcp.tool()
async def query_orders_by_customer(customer_name: str) -> str:
    """Search for orders by customer name (case-insensitive partial match).

    Args:
        customer_name: Full or partial customer name (e.g. "Contoso")
    """
    container = await get_container()
    query = "SELECT * FROM c WHERE CONTAINS(LOWER(c.customerName), LOWER(@name))"
    parameters = [{"name": "@name", "value": customer_name}]

    results = []
    async for item in container.query_items(query=query, parameters=parameters):
        results.append(_strip_cosmos_metadata(item))

    return json.dumps({"count": len(results), "orders": results}, indent=2, default=str)


@mcp.tool()
async def query_orders_by_status(status: str) -> str:
    """Query orders filtered by status.

    Args:
        status: Order status — one of: Processing, Shipped, Delivered, Cancelled
    """
    container = await get_container()
    query = "SELECT * FROM c WHERE c.status = @status"
    parameters = [{"name": "@status", "value": status}]

    results = []
    async for item in container.query_items(query=query, parameters=parameters):
        results.append(_strip_cosmos_metadata(item))

    return json.dumps({"count": len(results), "orders": results}, indent=2, default=str)


@mcp.tool()
async def list_customers() -> str:
    """List all unique customers with their order counts."""
    container = await get_container()
    query = "SELECT c.customerId, c.customerName, c.contactEmail FROM c"

    customers: dict[str, dict] = {}
    async for item in container.query_items(query=query):
        cid = item["customerId"]
        if cid not in customers:
            customers[cid] = {
                "customerId": cid,
                "customerName": item["customerName"],
                "contactEmail": item.get("contactEmail", ""),
                "orderCount": 0,
            }
        customers[cid]["orderCount"] += 1

    result = sorted(customers.values(), key=lambda x: x["customerName"])
    return json.dumps({"count": len(result), "customers": result}, indent=2)


# ============================================================================
# MCP Tools — Write
# ============================================================================


@mcp.tool()
async def create_order(
    customer_id: str,
    customer_name: str,
    contact_email: str,
    items: list[dict],
) -> str:
    """Create a new order.

    Args:
        customer_id: Customer ID (e.g. "contoso-001")
        customer_name: Customer display name
        contact_email: Customer contact email
        items: List of items — each dict must have: sku, name, qty, unitPrice
    """
    container = await get_container()

    total = sum(i.get("qty", 0) * i.get("unitPrice", 0) for i in items)
    order_num = uuid.uuid4().hex[:8]

    order = {
        "id": f"order-{order_num}",
        "customerId": customer_id,
        "customerName": customer_name,
        "contactEmail": contact_email,
        "items": items,
        "status": "Processing",
        "orderDate": datetime.now(timezone.utc).isoformat(),
        "totalAmount": round(total, 2),
    }

    created = await container.create_item(body=order)
    return json.dumps(
        {"message": "Order created", "order": _strip_cosmos_metadata(created)},
        indent=2,
        default=str,
    )


@mcp.tool()
async def update_order_status(order_id: str, customer_id: str, new_status: str) -> str:
    """Update the status of an existing order.

    Args:
        order_id: The order ID to update
        customer_id: The customer ID (partition key)
        new_status: New status — one of: Processing, Shipped, Delivered, Cancelled
    """
    valid = ("Processing", "Shipped", "Delivered", "Cancelled")
    if new_status not in valid:
        return json.dumps({"error": f"Invalid status. Must be one of: {valid}"})

    container = await get_container()
    try:
        item = await container.read_item(item=order_id, partition_key=customer_id)
        old_status = item["status"]
        item["status"] = new_status

        if new_status == "Delivered":
            item["deliveredDate"] = datetime.now(timezone.utc).isoformat()
        elif new_status == "Cancelled":
            item["cancelledDate"] = datetime.now(timezone.utc).isoformat()

        updated = await container.replace_item(item=order_id, body=item)
        return json.dumps(
            {
                "message": f"Status changed from {old_status} to {new_status}",
                "order": _strip_cosmos_metadata(updated),
            },
            indent=2,
            default=str,
        )
    except Exception as e:
        return json.dumps({"error": str(e)})


@mcp.tool()
async def cancel_order(order_id: str, customer_id: str, reason: str) -> str:
    """Cancel an existing order with a reason.

    Args:
        order_id: The order ID to cancel
        customer_id: The customer ID (partition key)
        reason: Reason for cancellation
    """
    container = await get_container()
    try:
        item = await container.read_item(item=order_id, partition_key=customer_id)

        if item["status"] == "Delivered":
            return json.dumps({"error": "Cannot cancel a delivered order"})
        if item["status"] == "Cancelled":
            return json.dumps({"error": "Order is already cancelled"})

        item["status"] = "Cancelled"
        item["cancelledDate"] = datetime.now(timezone.utc).isoformat()
        item["cancelReason"] = reason

        updated = await container.replace_item(item=order_id, body=item)
        return json.dumps(
            {"message": f"Order {order_id} cancelled", "order": _strip_cosmos_metadata(updated)},
            indent=2,
            default=str,
        )
    except Exception as e:
        return json.dumps({"error": str(e)})


# ============================================================================
# Entry point — local development
# ============================================================================

if __name__ == "__main__":
    print(f"Starting Customer Order Assistant MCP Server (streamable-http)")
    print(f"  Cosmos DB: {COSMOS_ENDPOINT}")
    print(f"  Database:  {COSMOS_DATABASE}")
    print(f"  Container: {COSMOS_CONTAINER}")
    print(f"  Endpoint:  http://127.0.0.1:8000/mcp")
    mcp.run(transport="streamable-http")
