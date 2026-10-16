import asyncio
from contextlib import asynccontextmanager
from datetime import timedelta

from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client

from . import config, db
from .crypto import decrypt


def err_text(e: BaseException) -> str:
    """Unwrap anyio ExceptionGroups into a readable one-line message."""
    while getattr(e, "exceptions", None):
        e = e.exceptions[0]
    if isinstance(e, asyncio.TimeoutError):
        return "timed out"
    return (str(e) or e.__class__.__name__)[:300]


@asynccontextmanager
async def open_session(row: dict, timeout_s: float):
    """Open an MCP client session to an upstream. Credentials are decrypted here, server side, only to build outbound headers."""
    headers = {}
    if row.get("secret_enc"):
        secret = decrypt(row["secret_enc"])
        if row["auth_type"] == "bearer":
            headers["Authorization"] = f"Bearer {secret}"
        elif row["auth_type"] == "header" and row.get("header_name"):
            headers[row["header_name"]] = secret
    t = timedelta(seconds=timeout_s)
    async with streamablehttp_client(row["url"], headers=headers, timeout=t, sse_read_timeout=t) as (read, write, _):
        async with ClientSession(read, write) as session:
            await session.initialize()
            yield session


async def refresh_server(server_id: int):
    row = await db.fetchrow("select * from servers where id=$1", server_id)
    if not row:
        return
    if not row["enabled"]:
        await db.execute("update servers set status='disabled', last_error=null, last_checked_at=now() where id=$1", server_id)
        return

    async def work():
        async with open_session(row, config.LIST_TIMEOUT) as s:
            res = await s.list_tools()
            return [{"name": t.name, "description": t.description or "", "inputSchema": t.inputSchema} for t in res.tools]

    try:
        tools = await asyncio.wait_for(work(), config.LIST_TIMEOUT)
        await db.execute("update servers set status='connected', last_error=null, tools=$2, last_checked_at=now() where id=$1", server_id, tools)
    except Exception as e:
        msg = f"list tools of {row['slug']} {err_text(e)}"
        await db.execute("update servers set status='unreachable', last_error=$2, last_checked_at=now() where id=$1", server_id, msg)


async def refresh_all():
    rows = await db.fetch("select id from servers")
    await asyncio.gather(*(refresh_server(r["id"]) for r in rows), return_exceptions=True)


async def health_loop():
    while True:
        try:
            await refresh_all()
        except Exception as e:
            print("health loop error", e, flush=True)
        await asyncio.sleep(config.HEALTH_INTERVAL)
