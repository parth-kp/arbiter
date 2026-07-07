"""A minimal agent service implementing the arbiter-agent/1 protocol.

It owns its own prompt and model call and knows nothing about Arbiter's internals:

    OPENROUTER_API_KEY=... uv run uvicorn examples.http_agent.server:app --port 8765
    arbiter run --env store --agent http --config configs/http.yaml --set golden --trials 1
"""

from __future__ import annotations

import os

import httpx
from fastapi import FastAPI
from pydantic import BaseModel

MODEL = os.environ.get("AGENT_MODEL", "anthropic/claude-haiku-5.5")
SYSTEM = "You are a concise, policy-abiding support agent. Use tools to look things up; never guess."

app = FastAPI(title="Example arbiter-agent/1 service")


class TurnRequest(BaseModel):
    protocol: str
    session_id: str
    turn: int
    context: str = ""
    messages: list[dict]
    tools: list[dict]


@app.post("/turn")
async def turn(req: TurnRequest) -> dict:
    messages = [{"role": "system", "content": f"{SYSTEM}\n\n{req.context}"}, *req.messages]
    async with httpx.AsyncClient(timeout=90) as client:
        r = await client.post(
            "https://openrouter.ai/api/v1/chat/completions",
            headers={"Authorization": f"Bearer {os.environ['OPENROUTER_API_KEY']}"},
            json={"model": MODEL, "messages": messages, "tools": req.tools, "temperature": 0},
        )
    r.raise_for_status()
    data = r.json()
    msg = data["choices"][0]["message"]
    usage = {"prompt_tokens": data["usage"]["prompt_tokens"], "completion_tokens": data["usage"]["completion_tokens"],
             "cost_usd": data["usage"].get("cost", 0.0)}
    if msg.get("tool_calls"):
        return {"type": "tool_calls", "usage": usage, "tool_calls": [
            {"id": tc["id"], "name": tc["function"]["name"], "arguments": tc["function"]["arguments"]}
            for tc in msg["tool_calls"]]}
    return {"type": "message", "content": msg.get("content") or "", "usage": usage}
