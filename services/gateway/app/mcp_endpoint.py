"""The gateway's own MCP endpoint (/mcp). Stateless Streamable HTTP; auth by per-user API key on every request."""
from contextvars import ContextVar
from typing import Optional

from mcp import types
from mcp.server.lowlevel import Server
from mcp.server.streamable_http_manager import StreamableHTTPSessionManager
from starlette.requests import Request
from starlette.responses import JSONResponse

from . import core, db
from .crypto import sha256

current_user: ContextVar[Optional[dict]] = ContextVar("current_user", default=None)
server = Server("team-mcp-gateway")


@server.list_tools()
async def _list_tools() -> list[types.Tool]:
    return [types.Tool(name=t["name"], description=t["description"], inputSchema=t["inputSchema"]) for t in await core.list_tools()]


@server.call_tool(validate_input=False)  # the upstream server validates arguments against its own schema
async def _call_tool(name: str, arguments: dict):
    user = current_user.get()
    r = await core.call_tool(user, "mcp", name, arguments or {})
    if r["is_error"]:
        raise RuntimeError(r["text"])  # the SDK turns this into an isError tool result
    return r["content"]


session_manager = StreamableHTTPSessionManager(app=server, json_response=True, stateless=True)


async def user_from_api_key(headers) -> Optional[dict]:
    auth = headers.get("authorization", "")
    raw = auth[7:].strip() if auth.lower().startswith("bearer ") else headers.get("x-api-key", "")
    if not raw.startswith("gw_"):
        return None
    h = sha256(raw)
    # Checked on every request: a revoked key (or deactivated user) is rejected immediately.
    user = await db.fetchrow(
        "select u.id,u.email,u.role from api_keys k join users u on u.id=k.user_id where k.key_hash=$1 and k.revoked_at is null and u.active", h)
    if user:
        await db.execute("update api_keys set last_used_at=now() where key_hash=$1", h)
    return user


class McpASGI:
    async def __call__(self, scope, receive, send):
        request = Request(scope)
        if request.method != "POST":
            return await JSONResponse({"jsonrpc": "2.0", "error": {"code": -32000, "message": "Method not allowed"}, "id": None}, status_code=405)(scope, receive, send)
        user = await user_from_api_key(request.headers)
        if not user:
            return await JSONResponse({"jsonrpc": "2.0", "error": {"code": -32001, "message": "Invalid or revoked API key"}, "id": None}, status_code=401)(scope, receive, send)
        token = current_user.set(user)
        try:
            await session_manager.handle_request(scope, receive, send)
        finally:
            current_user.reset(token)
