import json
from datetime import date

import httpx

from . import config, core


async def _llm(messages: list, tools: list) -> dict:
    headers = {"Content-Type": "application/json"}
    if config.LLM_API_KEY:
        headers["Authorization"] = f"Bearer {config.LLM_API_KEY}"
    body = {"model": config.LLM_MODEL, "messages": messages}
    if tools:
        body.update(tools=tools, tool_choice="auto")
    async with httpx.AsyncClient(timeout=90) as c:
        r = await c.post(f"{config.LLM_BASE_URL.rstrip('/')}/chat/completions", headers=headers, json=body)
    if r.status_code >= 400:
        raise RuntimeError(f"LLM {r.status_code}: {r.text[:300]}")
    return r.json()["choices"][0]["message"]


async def run_chat(user: dict, history: list[dict]) -> dict:
    """Tool loop: model -> tool calls (through the gateway core, as the logged-in user) -> results -> model."""
    if not config.LLM_BASE_URL or not config.LLM_MODEL:
        raise RuntimeError("Chat is not configured: set gateway.llm.baseUrl/model and the LLM API key secret.")
    tools = [{"type": "function", "function": {"name": t["name"], "description": t["description"][:900], "parameters": t["inputSchema"]}}
             for t in await core.list_tools()]
    messages = [{"role": "system", "content": f"You are the store assistant for a team. Use the provided tools to answer; never invent data. Today is {date.today().isoformat()}. Be concise."}]
    messages += [{"role": m["role"], "content": str(m["content"])} for m in history if m.get("role") in ("user", "assistant")]
    trace = []
    for _ in range(8):
        msg = await _llm(messages, tools)
        calls = msg.get("tool_calls") or []
        if not calls:
            return {"reply": msg.get("content") or "", "toolCalls": trace}
        messages.append({"role": "assistant", "content": msg.get("content"), "tool_calls": calls})
        for tc in calls:
            try:
                args = json.loads(tc["function"].get("arguments") or "{}")
            except json.JSONDecodeError:
                args = {}
            result = await core.call_tool(user, "chat", tc["function"]["name"], args)
            trace.append({"name": tc["function"]["name"], "args": args, "isError": result["is_error"], "result": result["text"][:1500]})
            messages.append({"role": "tool", "tool_call_id": tc["id"], "content": result["text"][:12000]})
    return {"reply": "Stopped after too many tool steps.", "toolCalls": trace}
