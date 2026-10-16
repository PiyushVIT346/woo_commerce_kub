"""WooCommerce MCP server (Streamable HTTP). Talks to the store through the WooCommerce REST API."""
import json
import os
from datetime import datetime
from typing import Literal, Optional
from zoneinfo import ZoneInfo

import httpx
import uvicorn
from mcp.server.fastmcp import FastMCP
from mcp.server.transport_security import TransportSecuritySettings
from starlette.responses import JSONResponse

PORT = int(os.environ.get("PORT", "3000"))
BASE = os.environ.get("WOOCOMMERCE_URL", "http://wordpress").rstrip("/")
CK = os.environ.get("WOO_CONSUMER_KEY", "")
CS = os.environ.get("WOO_CONSUMER_SECRET", "")
TOKEN = os.environ.get("MCP_AUTH_TOKEN", "")
TZ = os.environ.get("STORE_TIMEZONE", "UTC")

mcp = FastMCP(
    "woocommerce-mcp",
    stateless_http=True,
    json_response=True,
    host="0.0.0.0",
    port=PORT,
    transport_security=TransportSecuritySettings(enable_dns_rebinding_protection=False),
)


async def wc(method: str, path: str, query: Optional[dict] = None, body: Optional[dict] = None):
    params = {k: v for k, v in (query or {}).items() if v not in (None, "")}
    async with httpx.AsyncClient(timeout=15) as client:
        r = await client.request(
            method, f"{BASE}/wp-json/wc/v3{path}", params=params, json=body, auth=(CK, CS),
            # Cluster-internal hop: WooCommerce only accepts key/secret Basic auth when it thinks the request is SSL.
            headers={"X-Forwarded-Proto": "https"},
        )
    if r.status_code >= 400:
        raise RuntimeError(f"WooCommerce error: HTTP {r.status_code}: {r.text[:300]}")
    return r.json()


def slim_product(p: dict) -> dict:
    return {k: p.get(k) for k in ("id", "name", "sku", "price", "regular_price", "status", "stock_status", "permalink")}


def slim_order(o: dict) -> dict:
    b = o.get("billing") or {}
    return {
        "id": o["id"], "number": o.get("number"), "status": o.get("status"), "total": o.get("total"),
        "currency": o.get("currency"), "date_created": o.get("date_created"), "payment_method": o.get("payment_method_title"),
        "customer": f"{b.get('first_name', '')} {b.get('last_name', '')}".strip(), "email": b.get("email"),
        "items": [{"product_id": i["product_id"], "name": i["name"], "quantity": i["quantity"], "total": i["total"]} for i in o.get("line_items", [])],
    }


def dump(v) -> str:
    return json.dumps(v, indent=2)


@mcp.tool()
async def list_products(search: Optional[str] = None, status: Literal["any", "publish", "draft", "private"] = "any", per_page: int = 20) -> str:
    """List products in the WooCommerce store. Optionally search by text."""
    data = await wc("GET", "/products", {"search": search, "status": status, "per_page": max(1, min(per_page, 100))})
    return dump([slim_product(p) for p in data])


@mcp.tool()
async def create_product(name: str, regular_price: str, description: Optional[str] = None, sku: Optional[str] = None,
                         status: Literal["publish", "draft"] = "publish") -> str:
    """Create a simple product. regular_price is a decimal string like '19.99'. Published by default so it shows on the storefront."""
    body = {"name": name, "type": "simple", "regular_price": regular_price, "status": status}
    if description:
        body["description"] = description
    if sku:
        body["sku"] = sku
    return dump(slim_product(await wc("POST", "/products", body=body)))


@mcp.tool()
async def list_orders(today: bool = False, status: str = "any", after: Optional[str] = None, before: Optional[str] = None, per_page: int = 20) -> str:
    """List orders, newest first. Set today=true for orders created today (store timezone), or use after/before ISO dates."""
    if today:
        after = datetime.now(ZoneInfo(TZ)).strftime("%Y-%m-%dT00:00:00")
    data = await wc("GET", "/orders", {"status": status, "after": after, "before": before, "per_page": max(1, min(per_page, 100)), "orderby": "date", "order": "desc"})
    return dump([slim_order(o) for o in data])


@mcp.tool()
async def get_order(id: int) -> str:
    """Get one order by its numeric id."""
    return dump(slim_order(await wc("GET", f"/orders/{id}")))


@mcp.tool()
async def update_order_status(id: int, status: Literal["pending", "processing", "on-hold", "completed", "cancelled", "refunded", "failed"]) -> str:
    """Change an order's status."""
    return dump(slim_order(await wc("PUT", f"/orders/{id}", body={"status": status})))


class Guard:
    """Health endpoint + shared bearer token (only the gateway holds it)."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] == "http":
            if scope["path"] == "/healthz":
                return await JSONResponse({"ok": True})(scope, receive, send)
            got = dict(scope["headers"]).get(b"authorization", b"").decode()
            if TOKEN and got != f"Bearer {TOKEN}":
                return await JSONResponse({"error": "unauthorized"}, status_code=401)(scope, receive, send)
        await self.app(scope, receive, send)


app = Guard(mcp.streamable_http_app())

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=PORT, log_level="info")
