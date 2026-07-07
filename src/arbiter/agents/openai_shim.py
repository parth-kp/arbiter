"""An httpx transport that makes any OpenAI-SDK-based agent framework go through Arbiter's LLM layer.

Pass ``httpx.AsyncClient(transport=ArbiterTransport(...))`` as the framework's HTTP client and every
``/chat/completions`` request is served by ``LLMClient`` instead: recorded to the cassette, replayable offline,
counted against the budget, and attributed to the trial.
"""

from __future__ import annotations

import json

import httpx

from arbiter.llm.client import LLMClient
from arbiter.llm.types import CallRecord, ChatRequest, Message, ToolCall, ToolSpec


def _content(c) -> str | None:
    if c is None or isinstance(c, str):
        return c
    if isinstance(c, list):
        return "".join(p.get("text", "") for p in c if isinstance(p, dict))
    return str(c)


def request_from_openai(body: dict) -> ChatRequest:
    msgs = []
    for m in body.get("messages", []):
        calls = None
        if m.get("tool_calls"):
            calls = []
            for tc in m["tool_calls"]:
                raw = tc["function"].get("arguments") or "{}"
                try:
                    args = json.loads(raw)
                except json.JSONDecodeError:
                    args = {"_malformed_json": raw}
                calls.append(ToolCall(id=tc["id"], name=tc["function"]["name"], arguments=args, raw_arguments=raw))
        role = "system" if m["role"] == "developer" else m["role"]
        msgs.append(Message(role=role, content=_content(m.get("content")), tool_calls=calls,
                            tool_call_id=m.get("tool_call_id"), name=m.get("name") if role == "tool" else None))
    tools = [ToolSpec(name=t["function"]["name"], description=t["function"].get("description", ""),
                      parameters=t["function"].get("parameters") or {"type": "object", "properties": {}})
             for t in body.get("tools") or []]
    return ChatRequest(model=body["model"], messages=msgs, tools=tools or None,
                       temperature=body.get("temperature") if body.get("temperature") is not None else 0.0,
                       max_tokens=body.get("max_tokens") or body.get("max_completion_tokens") or 1024)


class ArbiterTransport(httpx.AsyncBaseTransport):
    def __init__(self, llm: LLMClient):
        self.llm = llm
        self.trial_key = "unset"
        self.on_call = None
        self._n = 0

    def bind(self, trial_key: str, on_call) -> None:
        if trial_key != self.trial_key:
            self._n = 0
        self.trial_key, self.on_call = trial_key, on_call

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        if not request.url.path.endswith("/chat/completions"):
            return httpx.Response(404, json={"error": {"message": f"shim only serves chat completions: {request.url}"}})
        body = json.loads(request.content or b"{}")
        if body.get("stream"):
            return httpx.Response(400, json={"error": {"message": "streaming is not supported by the Arbiter shim"}})
        req = request_from_openai(body)
        n = self._n
        self._n += 1
        calls: list[CallRecord] = []
        resp = await self.llm.complete(req, trial_key=f"{self.trial_key}/sdk{n}", purpose="agent",
                                       on_call=calls.append)
        if self.on_call:
            for c in calls:
                self.on_call(c)
        msg = resp.message
        out = {
            "id": f"chatcmpl-arbiter-{n}",
            "object": "chat.completion",
            "created": 0,
            "model": resp.model,
            "choices": [{
                "index": 0,
                "finish_reason": "tool_calls" if msg.tool_calls else (resp.finish_reason or "stop"),
                "message": {k: v for k, v in msg.to_openai().items() if k in ("role", "content", "tool_calls")},
            }],
            "usage": {"prompt_tokens": resp.usage.prompt_tokens, "completion_tokens": resp.usage.completion_tokens,
                      "total_tokens": resp.usage.prompt_tokens + resp.usage.completion_tokens},
        }
        return httpx.Response(200, json=out)
