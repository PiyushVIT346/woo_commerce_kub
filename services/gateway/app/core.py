"""Shared by the external MCP endpoint and the chat agent: every call is routed, timed and audited here."""
import asyncio
import time
from datetime import timedelta

from mcp import types

from . import config, db
from .upstream import err_text, open_session

SEP = "__"  # gateway tool name = <server-slug>__<tool>; slugs cannot contain "_"


async def list_tools() -> list[dict]:
    rows = await db.fetch("select slug,name,tools from servers where enabled and status='connected' order by slug")
    return [
        {"name": f"{r['slug']}{SEP}{t['name']}", "description": f"[{r['name']}] {t.get('description') or ''}".strip(),
         "inputSchema": t.get("inputSchema") or {"type": "object", "properties": {}}}
        for r in rows for t in r["tools"]
    ]


def text_of(content) -> str:
    return "\n".join(c.text for c in content if getattr(c, "type", "") == "text")


async def call_tool(user: dict, source: str, full_name: str, args: dict) -> dict:
    started = time.monotonic()
    slug, tool, status, error = "?", full_name, "success", None
    content: list = []
    is_error = False
    try:
        i = full_name.find(SEP)
        if i < 1:
            raise ValueError(f'Unknown tool "{full_name}". Tool names look like <server>{SEP}<tool>.')
        slug, tool = full_name[:i], full_name[i + len(SEP):]
        row = await db.fetchrow("select * from servers where slug=$1", slug)
        if not row or not row["enabled"]:
            raise ValueError(f'Server "{slug}" does not exist or is disabled.')

        async def work():
            async with open_session(row, config.CALL_TIMEOUT) as s:
                return await s.call_tool(tool, args or {}, read_timeout_seconds=timedelta(seconds=config.CALL_TIMEOUT))

        result = await asyncio.wait_for(work(), config.CALL_TIMEOUT)
        content, is_error = list(result.content), bool(result.isError)
        if is_error:
            status, error = "error", text_of(content)[:300]
    except asyncio.TimeoutError:
        status, is_error = "timeout", True
        error = f"tool {tool} on {slug} timed out after {config.CALL_TIMEOUT:g}s"
    except Exception as e:
        status, is_error, error = "error", True, err_text(e)
    finally:
        try:
            await db.execute(
                "insert into audit_log(user_id,user_email,source,server_slug,tool,duration_ms,status,error) values($1,$2,$3,$4,$5,$6,$7,$8)",
                user["id"], user["email"], source, slug, tool, int((time.monotonic() - started) * 1000), status, error)
        except Exception as e:
            print("audit write failed", e, flush=True)
    if is_error and not content:
        content = [types.TextContent(type="text", text=f"Gateway: {error}")]
    return {"is_error": is_error, "content": content, "text": text_of(content)}
