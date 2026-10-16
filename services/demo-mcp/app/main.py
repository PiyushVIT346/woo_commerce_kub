"""Demo MCP server. MODE=notes -> add_note/list_notes/echo ; MODE=clock -> get_time/echo.
Both modes expose `echo` on purpose, to demonstrate the gateway's tool-name collision handling."""
import json
import os
from datetime import datetime, timezone
from typing import Optional
from zoneinfo import ZoneInfo

import uvicorn
from mcp.server.fastmcp import FastMCP
from mcp.server.transport_security import TransportSecuritySettings
from starlette.responses import JSONResponse

PORT = int(os.environ.get("PORT", "3000"))
MODE = os.environ.get("MODE", "notes")
TOKEN = os.environ.get("MCP_AUTH_TOKEN", "")

mcp = FastMCP(
    f"demo-{MODE}", stateless_http=True, json_response=True, host="0.0.0.0", port=PORT,
    transport_security=TransportSecuritySettings(enable_dns_rebinding_protection=False),
)
notes: list[dict] = []


@mcp.tool()
def echo(message: str) -> str:
    """Echo a message back, tagged with the name of the server that handled it."""
    return f"[{MODE}] {message}"


if MODE == "notes":
    @mcp.tool()
    def add_note(text: str) -> str:
        """Save a short note."""
        n = {"id": len(notes) + 1, "text": text, "at": datetime.now(timezone.utc).isoformat()}
        notes.append(n)
        return json.dumps(n)

    @mcp.tool()
    def list_notes() -> str:
        """List all saved notes."""
        return json.dumps(notes, indent=2)
else:
    @mcp.tool()
    def get_time(timezone_name: Optional[str] = None) -> str:
        """Current date and time, optionally in an IANA timezone name such as Asia/Kolkata (default UTC)."""
        try:
            return datetime.now(ZoneInfo(timezone_name or "UTC")).strftime("%A, %d %B %Y %H:%M:%S %Z")
        except Exception:
            raise ValueError(f"Unknown timezone: {timezone_name}")


class Guard:
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
