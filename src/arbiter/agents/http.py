"""Adapter for any agent behind an HTTP endpoint speaking the arbiter-agent/1 protocol (docs/HTTP_PROTOCOL.md).

The endpoint is stateless: every request carries the full conversation, including earlier tool calls and their
results. Arbiter executes the tools, so the agent never touches environment state directly.
"""

from __future__ import annotations

import hashlib
import json
import time
import uuid

import httpx

from arbiter.agents.openai_chat import STEP_LIMIT_REPLY
from arbiter.core.agent import Agent, AgentConfig, AgentDeps, TurnContext
from arbiter.llm.types import CallRecord, ChatResponse, Message, ToolCall, Usage

PROTOCOL = "arbiter-agent/1"


class HTTPAgentError(RuntimeError):
    pass


class HTTPAgent(Agent):
    def __init__(self, config: AgentConfig, deps: AgentDeps, transport: httpx.AsyncBaseTransport | None = None):
        super().__init__(config)
        if not config.endpoint:
            raise ValueError("http agent needs agent.endpoint")
        self.cassette = deps.llm.cassette if deps.llm is not None else None
        self.history: list[Message] = []
        self.session_id = uuid.uuid4().hex
        self._client = httpx.AsyncClient(timeout=120, transport=transport)

    async def aclose(self) -> None:
        await self._client.aclose()

    async def respond(self, ctx: TurnContext) -> str:
        self.history.append(ctx.messages[-1])
        for step in range(self.config.max_tool_steps):
            body = {
                "protocol": PROTOCOL,
                "session_id": ctx.trial_key,
                "turn": ctx.turn,
                "context": ctx.system_context,
                "messages": [m.to_openai() for m in self.history],
                "tools": [t.to_openai() for t in ctx.tools],
            }
            msg = await self._post(body, f"{ctx.trial_key}/http/t{ctx.turn}s{step}", ctx)
            self.history.append(msg)
            if not msg.tool_calls:
                return msg.content or ""
            for tc in msg.tool_calls:
                result = ctx.call_tool(tc.name, tc.arguments)
                self.history.append(Message(role="tool", tool_call_id=tc.id, name=tc.name, content=result.as_text()))
        return STEP_LIMIT_REPLY

    async def _post(self, body: dict, trial_key: str, ctx: TurnContext) -> Message:
        key = hashlib.sha256(json.dumps({"http": body | {"session_id": ""}, "trial": trial_key},
                                        sort_keys=True).encode()).hexdigest()
        cached = self.cassette.lookup(key) if self.cassette is not None else None
        if cached is not None:
            resp = cached
        else:
            started = time.perf_counter()
            r = await self._client.post(self.config.endpoint, json=body)
            if r.status_code != 200:
                raise HTTPAgentError(f"agent endpoint returned {r.status_code}: {r.text[:200]}")
            resp = ChatResponse(message=parse_reply(r.json()), model=self.config.model or "http-agent",
                                provider="http", latency_ms=(time.perf_counter() - started) * 1000,
                                usage=_usage(r.json()))
            if self.cassette is not None:
                self.cassette.store(key, resp)
        ctx.on_call(CallRecord(purpose="agent", model=resp.model, provider=resp.provider,
                               prompt_tokens=resp.usage.prompt_tokens, completion_tokens=resp.usage.completion_tokens,
                               cost_usd=resp.usage.cost_usd, latency_ms=resp.latency_ms,
                               from_cassette=resp.from_cassette))
        return resp.message


def parse_reply(data: dict) -> Message:
    kind = data.get("type")
    if kind == "tool_calls":
        calls = []
        for i, tc in enumerate(data.get("tool_calls") or []):
            args = tc.get("arguments") or {}
            if isinstance(args, str):
                try:
                    args = json.loads(args)
                except json.JSONDecodeError:
                    args = {"_malformed_json": args}
            calls.append(ToolCall(id=tc.get("id") or f"call_{i}", name=tc["name"], arguments=args))
        if not calls:
            raise HTTPAgentError("tool_calls reply contained no calls")
        return Message(role="assistant", tool_calls=calls)
    if kind == "message":
        return Message(role="assistant", content=data.get("content") or "")
    raise HTTPAgentError(f"unknown reply type {kind!r}; expected 'message' or 'tool_calls'")


def _usage(data: dict) -> Usage:
    u = data.get("usage") or {}
    return Usage(prompt_tokens=int(u.get("prompt_tokens") or 0), completion_tokens=int(u.get("completion_tokens") or 0),
                 cost_usd=float(u.get("cost_usd") or 0.0), cost_source="provider" if "cost_usd" in u else "none")
