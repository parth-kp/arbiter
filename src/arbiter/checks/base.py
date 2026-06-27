from __future__ import annotations

import json
from typing import Any, ClassVar, Literal

from pydantic import BaseModel, Field

from arbiter.core.environment import Approval, Environment, RuleEvent
from arbiter.core.transcript import ToolCallRecord, TranscriptEvent

CheckKind = Literal["final_state", "tool_call", "policy", "transcript", "judge"]


class CheckContext(BaseModel):
    model_config = {"arbitrary_types_allowed": True}

    scenario_id: str
    env: Environment
    initial_state: dict[str, Any]
    final_state: dict[str, Any]
    tool_calls: list[ToolCallRecord]
    events: list[TranscriptEvent]
    rule_events: list[RuleEvent]
    approvals: list[Approval]
    user_knowledge: str = ""

    @property
    def assistant_texts(self) -> list[str]:
        return [e.content or "" for e in self.events if e.kind == "assistant"]

    @property
    def user_texts(self) -> list[str]:
        return [e.content or "" for e in self.events if e.kind == "user"]

    def tool_output_text(self) -> str:
        return "\n".join(json.dumps(c.output, default=str) for c in self.tool_calls if c.ok)


class CheckResult(BaseModel):
    name: str
    type: str
    kind: CheckKind
    passed: bool
    required: bool = True
    detail: str = ""
    reasoning: str | None = None


class Check(BaseModel):
    """Base for all checks. Subclasses set ``type`` and ``kind`` and implement ``evaluate``."""

    model_config = {"extra": "forbid"}

    type: str
    name: str | None = None
    required: bool = True
    kind: ClassVar[CheckKind] = "final_state"

    def label(self) -> str:
        return self.name or self.type

    def evaluate(self, ctx: CheckContext) -> CheckResult:
        raise NotImplementedError

    def result(self, passed: bool, detail: str = "") -> CheckResult:
        return CheckResult(name=self.label(), type=self.type, kind=self.kind, passed=passed, required=self.required,
                           detail=detail)


_REGISTRY: dict[str, type[Check]] = {}


def register_check(cls: type[Check]) -> type[Check]:
    type_value = cls.model_fields["type"].default
    if not isinstance(type_value, str):
        raise TypeError(f"{cls.__name__} must give `type` a string default")
    _REGISTRY[type_value] = cls
    return cls


def parse_check(data: dict[str, Any] | Check) -> Check:
    if isinstance(data, Check):
        return data
    t = data.get("type")
    if t not in _REGISTRY:
        raise ValueError(f"unknown check type {t!r}; known: {sorted(_REGISTRY)}")
    return _REGISTRY[t].model_validate(data)


def check_types() -> dict[str, type[Check]]:
    return dict(_REGISTRY)


class _Missing:
    def __repr__(self) -> str:
        return "<missing>"


MISSING = _Missing()


def resolve_path(data: Any, path: str) -> Any:
    cur = data
    for part in path.split(".") if path else []:
        if isinstance(cur, dict):
            if part not in cur:
                return MISSING
            cur = cur[part]
        elif isinstance(cur, list):
            try:
                cur = cur[int(part)]
            except (ValueError, IndexError):
                return MISSING
        else:
            return MISSING
    return cur


def compare(actual: Any, op: str, expected: Any) -> bool:
    if op == "exists":
        return actual is not MISSING
    if op == "absent":
        return actual is MISSING
    if actual is MISSING:
        return False
    match op:
        case "eq":
            return actual == expected
        case "ne":
            return actual != expected
        case "gt":
            return actual > expected
        case "gte":
            return actual >= expected
        case "lt":
            return actual < expected
        case "lte":
            return actual <= expected
        case "in":
            return actual in expected
        case "not_in":
            return actual not in expected
        case "contains":
            return expected in actual
        case "not_contains":
            return expected not in actual
        case "len_eq":
            return len(actual) == expected
        case "matches":
            import re

            return re.search(str(expected), str(actual), re.I) is not None
    raise ValueError(f"unknown operator {op!r}")


Op = Literal["eq", "ne", "gt", "gte", "lt", "lte", "in", "not_in", "contains", "not_contains", "len_eq",
             "exists", "absent", "matches"]


def args_match(actual: dict[str, Any], expected: dict[str, Any]) -> bool:
    for k, v in expected.items():
        got = resolve_path(actual, k)
        if isinstance(v, dict) and "op" in v:
            if not compare(got, v["op"], v.get("value")):
                return False
        elif isinstance(got, str) and isinstance(v, str):
            if got.strip().lower() != v.strip().lower():
                return False
        elif got != v:
            return False
    return True


__all__ = ["Check", "CheckContext", "CheckResult", "Field", "MISSING", "Op", "args_match", "check_types", "compare",
           "parse_check", "register_check", "resolve_path"]
