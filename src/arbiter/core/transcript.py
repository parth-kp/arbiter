from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


class TranscriptEvent(BaseModel):
    kind: Literal["user", "assistant", "tool_call", "tool_result", "system", "error"]
    turn: int
    content: str | None = None
    tool: str | None = None
    arguments: dict[str, Any] | None = None
    result: Any = None
    ok: bool | None = None
    error_kind: str | None = None
    rule: str | None = None
    t_ms: float = 0.0


class ToolCallRecord(BaseModel):
    turn: int
    index: int
    tool: str
    arguments: dict[str, Any] = Field(default_factory=dict)
    ok: bool
    error: str | None = None
    error_kind: str | None = None
    rule: str | None = None
    output: Any = None
