"""Scripted stand-ins for model providers so the framework can be tested fully offline."""

from __future__ import annotations

import json
from collections.abc import Callable

from arbiter.llm.types import ChatRequest, ChatResponse, Message, ToolCall, Usage


def tool_call(name: str, **args) -> Message:
    return Message(role="assistant", content=None,
                   tool_calls=[ToolCall(id=f"c_{name}", name=name, arguments=args, raw_arguments=json.dumps(args))])


def say(text: str) -> Message:
    return Message(role="assistant", content=text)


class FakeChain:
    """Answers each request with policy(request) -> Message. Records every request it saw."""

    def __init__(self, policy: Callable[[ChatRequest], Message], cost: float = 0.001, latency_ms: float = 100.0):
        self.policy = policy
        self.cost = cost
        self.latency_ms = latency_ms
        self.requests: list[ChatRequest] = []

    async def complete(self, req: ChatRequest) -> ChatResponse:
        self.requests.append(req)
        return ChatResponse(message=self.policy(req), model=req.model, provider="fake", latency_ms=self.latency_ms,
                            usage=Usage(prompt_tokens=100, completion_tokens=20, cost_usd=self.cost,
                                        cost_source="provider"))

    async def aclose(self) -> None:
        return None


def scripted_agent(*steps: Message) -> Callable[[ChatRequest], Message]:
    """Plays steps in order, indexed by how many assistant messages the agent has produced so far."""

    def policy(req: ChatRequest) -> Message:
        produced = sum(1 for m in req.messages if m.role == "assistant")
        return steps[min(produced, len(steps) - 1)]

    return policy
