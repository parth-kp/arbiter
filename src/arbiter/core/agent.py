from __future__ import annotations

import time
from abc import ABC, abstractmethod
from collections.abc import Callable
from typing import Any

from pydantic import BaseModel, Field

from arbiter.core.environment import Environment, ToolResult
from arbiter.core.transcript import ToolCallRecord, TranscriptEvent
from arbiter.llm.client import LLMClient
from arbiter.llm.types import CallRecord, Message, ToolSpec


class AgentConfig(BaseModel):
    """Everything that defines the agent under test. Saved verbatim with every run."""

    model_config = {"extra": "allow"}

    type: str = "reference"
    model: str = "anthropic/claude-haiku-5.5"
    prompt_version: str = "v1"
    tool_descriptions: str = "default"
    temperature: float = 0.0
    max_tokens: int = 4096
    # Hidden reasoning tokens count against max_tokens on reasoning models; an explicit budget keeps the visible
    # reply from being starved. 0 disables reasoning, None leaves the provider default.
    reasoning_max_tokens: int | None = 1024
    max_tool_steps: int = 12
    retrieval: bool = True
    injection_defense: bool = False
    base_url: str | None = None
    endpoint: str | None = None
    system_prompt: str | None = None


def reasoning_param(budget: int | None) -> dict | None:
    if budget is None:
        return None
    return {"enabled": False} if budget == 0 else {"max_tokens": budget}


class TurnContext:
    """What an agent sees during one user turn. Tools are executed by Arbiter, never by the agent."""

    def __init__(self, *, env: Environment, messages: list[Message], tools: list[ToolSpec], turn: int,
                 trial_key: str, llm: LLMClient | None, on_call: Callable[[CallRecord], None],
                 events: list[TranscriptEvent], tool_calls: list[ToolCallRecord], started: float):
        self.env = env
        self.messages = messages
        self.tools = tools
        self.turn = turn
        self.trial_key = trial_key
        self.llm = llm
        self.on_call = on_call
        self._events = events
        self._tool_calls = tool_calls
        self._started = started
        self._allowed = {t.name for t in tools}
        self.steps = 0

    @property
    def system_context(self) -> str:
        return self.env.system_context()

    def call_tool(self, name: str, arguments: dict[str, Any]) -> ToolResult:
        self.steps += 1
        now = (time.perf_counter() - self._started) * 1000
        self._events.append(TranscriptEvent(kind="tool_call", turn=self.turn, tool=name, arguments=arguments, t_ms=now))
        result = self.env.call_tool(name, arguments, allowed=self._allowed)
        self._events.append(TranscriptEvent(
            kind="tool_result", turn=self.turn, tool=name, result=result.output if result.ok else result.error,
            ok=result.ok, error_kind=result.error_kind, rule=result.rule,
            t_ms=(time.perf_counter() - self._started) * 1000,
        ))
        self._tool_calls.append(ToolCallRecord(
            turn=self.turn, index=len(self._tool_calls), tool=name, arguments=arguments, ok=result.ok,
            error=result.error, error_kind=result.error_kind, rule=result.rule, output=result.output,
        ))
        return result


class Agent(ABC):
    """An agent under test. One instance is created per trial, so it may keep conversation state."""

    def __init__(self, config: AgentConfig):
        self.config = config

    @abstractmethod
    async def respond(self, ctx: TurnContext) -> str:
        """Handle the latest user message (ctx.messages[-1]); call tools via ctx.call_tool; return the reply."""

    async def aclose(self) -> None:
        return None


class AgentDeps(BaseModel):
    model_config = {"arbitrary_types_allowed": True}

    llm: Any = None
    prompts_dir: Any = None
    extra: dict[str, Any] = Field(default_factory=dict)


AgentFactory = Callable[[AgentConfig, AgentDeps], Agent]
