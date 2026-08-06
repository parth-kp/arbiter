from __future__ import annotations

import hashlib
import json
from typing import Any, Literal

from pydantic import BaseModel, Field


class ToolCall(BaseModel):
    id: str
    name: str
    arguments: dict[str, Any] = Field(default_factory=dict)
    raw_arguments: str | None = None


class Message(BaseModel):
    role: Literal["system", "user", "assistant", "tool"]
    content: str | None = None
    tool_calls: list[ToolCall] | None = None
    tool_call_id: str | None = None
    name: str | None = None

    def to_openai(self) -> dict[str, Any]:
        content = self.content
        if content is not None and not content.strip() and not self.tool_calls:
            # Anthropic rejects empty text blocks; an empty reply (e.g. cut off at max_tokens) must not crash the
            # next request in the conversation.
            content = "(empty message)"
        out: dict[str, Any] = {"role": self.role, "content": content}
        if self.tool_calls:
            out["tool_calls"] = [
                {
                    "id": tc.id,
                    "type": "function",
                    "function": {
                        "name": tc.name,
                        "arguments": tc.raw_arguments
                        if tc.raw_arguments is not None
                        else json.dumps(tc.arguments, sort_keys=True),
                    },
                }
                for tc in self.tool_calls
            ]
        if self.tool_call_id:
            out["tool_call_id"] = self.tool_call_id
        if self.name and self.role == "tool":
            out["name"] = self.name
        return out


class ToolSpec(BaseModel):
    name: str
    description: str
    parameters: dict[str, Any]

    def to_openai(self) -> dict[str, Any]:
        return {
            "type": "function",
            "function": {"name": self.name, "description": self.description, "parameters": self.parameters},
        }


class ChatRequest(BaseModel):
    model: str
    messages: list[Message]
    tools: list[ToolSpec] | None = None
    temperature: float = 0.0
    max_tokens: int = 1024
    response_format: dict[str, Any] | None = None
    prompt_cache: bool = True

    def to_openai(self) -> dict[str, Any]:
        messages = [m.to_openai() for m in self.messages]
        if self.prompt_cache and self.model.startswith("anthropic/"):
            _mark_cache_breakpoints(messages)
        body: dict[str, Any] = {
            "model": self.model,
            "messages": messages,
            "temperature": self.temperature,
            "max_tokens": self.max_tokens,
        }
        if self.tools:
            body["tools"] = [t.to_openai() for t in self.tools]
        if self.response_format:
            body["response_format"] = self.response_format
        return body

    def cache_key(self, trial_key: str) -> str:
        # trial_key keeps trial k from replaying trial 0's sampled response; provider is deliberately
        # excluded so a cassette recorded via one gateway replays regardless of which served it.
        payload = json.dumps({"req": self.to_openai(), "trial": trial_key}, sort_keys=True)
        return hashlib.sha256(payload.encode()).hexdigest()


def _mark_cache_breakpoints(messages: list[dict[str, Any]]) -> None:
    """Anthropic prompt caching via OpenRouter: mark the system prompt and the newest message as cache breakpoints.

    An agent loop resends an ever-growing prefix on every step, so caching it cuts input cost sharply. Anthropic
    allows at most four breakpoints; we use two.
    """
    targets = []
    if messages and messages[0]["role"] == "system":
        targets.append(messages[0])
    if len(messages) > 1 and messages[-1]["role"] in ("user", "tool"):
        targets.append(messages[-1])
    for m in targets:
        if isinstance(m.get("content"), str) and m["content"]:
            m["content"] = [{"type": "text", "text": m["content"], "cache_control": {"type": "ephemeral"}}]


class Usage(BaseModel):
    prompt_tokens: int = 0
    completion_tokens: int = 0
    cached_tokens: int = 0
    cost_usd: float = 0.0
    cost_source: Literal["provider", "price_table", "none"] = "none"


class ChatResponse(BaseModel):
    message: Message
    usage: Usage = Field(default_factory=Usage)
    model: str
    provider: str = "unknown"
    latency_ms: float = 0.0
    finish_reason: str | None = None
    from_cassette: bool = False


class CallRecord(BaseModel):
    """One model call as seen by the run: who served it, what it cost, and why it was made."""

    purpose: str
    model: str
    provider: str
    prompt_tokens: int
    completion_tokens: int
    cost_usd: float
    latency_ms: float
    from_cassette: bool
