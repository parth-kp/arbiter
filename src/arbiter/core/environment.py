from __future__ import annotations

import copy
import inspect
import json
import typing
from collections.abc import Callable
from pathlib import Path
from typing import Any, ClassVar

import yaml
from pydantic import BaseModel, Field, ValidationError

from arbiter.core.policy_index import PolicyDoc, PolicyIndex
from arbiter.llm.types import ToolSpec


class ToolError(Exception):
    """A normal, recoverable failure the agent should read and react to (e.g. "order not found")."""


class RuleViolation(Exception):
    """A business rule blocked the action. Recorded as a policy attempt even though nothing changed."""

    def __init__(self, rule: str, message: str):
        super().__init__(message)
        self.rule = rule
        self.message = message


class RuleEvent(BaseModel):
    rule: str
    tool: str
    message: str
    arguments: dict[str, Any] = Field(default_factory=dict)


class Approval(BaseModel):
    id: str
    action: str
    amount: float | None = None
    reason: str = ""
    payload: dict[str, Any] = Field(default_factory=dict)
    status: str = "pending"


class ToolResult(BaseModel):
    tool: str
    ok: bool
    output: Any = None
    error: str | None = None
    error_kind: str | None = None  # "validation" | "tool_error" | "rule" | "fault" | "unknown_tool"
    rule: str | None = None
    untrusted: bool = False

    def as_text(self) -> str:
        if self.ok:
            return self.output if isinstance(self.output, str) else json.dumps(self.output, default=str)
        prefix = "POLICY BLOCKED" if self.error_kind == "rule" else "ERROR"
        return f"{prefix}: {self.error}"


class Fault(BaseModel):
    """Scenario-injected tool failure, e.g. a carrier API that times out the first time it is called."""

    tool: str
    error: str
    times: int = 1


class ToolDef(BaseModel):
    model_config = {"arbitrary_types_allowed": True}

    name: str
    description: str
    args_model: type[BaseModel]
    method_name: str
    mutates: bool = False
    untrusted_output: bool = False
    retrieval: bool = False

    def spec(self, description: str | None = None) -> ToolSpec:
        schema = self.args_model.model_json_schema()
        schema.pop("title", None)
        for prop in schema.get("properties", {}).values():
            prop.pop("title", None)
        return ToolSpec(name=self.name, description=description or self.description, parameters=schema)


def tool(name: str | None = None, *, mutates: bool = False, untrusted_output: bool = False,
         retrieval: bool = False) -> Callable:
    """Mark an Environment method as an agent-callable tool.

    The method takes one argument annotated with a Pydantic model; that model is the tool's schema and
    its docstring is the tool's default description.
    """

    def decorate(fn: Callable) -> Callable:
        fn.__arbiter_tool__ = {  # type: ignore[attr-defined]
            "name": name or fn.__name__,
            "mutates": mutates,
            "untrusted_output": untrusted_output,
            "retrieval": retrieval,
        }
        return fn

    return decorate


def predicate(name: str | None = None) -> Callable:
    """Mark an Environment method as a named final-state predicate usable from scenario YAML."""

    def decorate(fn: Callable) -> Callable:
        fn.__arbiter_predicate__ = name or fn.__name__  # type: ignore[attr-defined]
        return fn

    return decorate


def deep_merge(base: Any, patch: Any) -> Any:
    if isinstance(base, dict) and isinstance(patch, dict):
        out = dict(base)
        for k, v in patch.items():
            if v is None:
                out.pop(k, None)
            else:
                out[k] = deep_merge(base.get(k), v) if k in base else copy.deepcopy(v)
        return out
    return copy.deepcopy(patch)


class Environment:
    """Base class for a simulated environment.

    Subclasses set ``name``, ``description``, ``State`` (a Pydantic model) and ``fixtures_dir``, then
    declare tools with ``@tool`` and business rules by raising ``RuleViolation`` inside tools. Rules live
    here, in code, so they hold no matter what the agent does.
    """

    name: ClassVar[str] = "base"
    description: ClassVar[str] = ""
    State: ClassVar[type[BaseModel]]
    fixtures_dir: ClassVar[Path | None] = None

    def __init__(self, state: BaseModel, *, faults: list[Fault] | None = None):
        self.state = state
        self.rule_events: list[RuleEvent] = []
        self.approvals: list[Approval] = []
        self._faults = [f.model_copy() for f in (faults or [])]
        self._policy_index: PolicyIndex | None = None

    @classmethod
    def load_snapshot(cls, name: str = "default") -> dict[str, Any]:
        if cls.fixtures_dir is None:
            raise FileNotFoundError(f"{cls.name} has no fixtures_dir")
        for ext in (".yaml", ".yml", ".json"):
            path = Path(cls.fixtures_dir) / f"{name}{ext}"
            if path.exists():
                text = path.read_text()
                return json.loads(text) if ext == ".json" else yaml.safe_load(text)
        raise FileNotFoundError(f"snapshot {name!r} not found in {cls.fixtures_dir}")

    @classmethod
    def build_state(cls, snapshot: str = "default", patch: dict | None = None) -> dict[str, Any]:
        data = cls.load_snapshot(snapshot)
        return deep_merge(data, patch) if patch else data

    @classmethod
    def from_state(cls, data: dict[str, Any], *, faults: list[Fault] | None = None) -> Environment:
        return cls(cls.State.model_validate(copy.deepcopy(data)), faults=faults)

    def dump_state(self) -> dict[str, Any]:
        return self.state.model_dump(mode="json")

    @classmethod
    def tool_defs(cls) -> list[ToolDef]:
        defs = []
        for attr, fn in inspect.getmembers(cls, predicate=inspect.isfunction):
            meta = getattr(fn, "__arbiter_tool__", None)
            if not meta:
                continue
            hints = typing.get_type_hints(fn)
            params = [p for p in inspect.signature(fn).parameters if p != "self"]
            if len(params) != 1 or not (isinstance(hints.get(params[0]), type)
                                        and issubclass(hints[params[0]], BaseModel)):
                raise TypeError(f"tool {cls.__name__}.{attr} must take exactly one Pydantic-model argument")
            defs.append(ToolDef(
                name=meta["name"], description=inspect.cleandoc(fn.__doc__ or meta["name"]),
                args_model=hints[params[0]], method_name=attr, mutates=meta["mutates"],
                untrusted_output=meta["untrusted_output"], retrieval=meta["retrieval"],
            ))
        return sorted(defs, key=lambda d: d.name)

    @classmethod
    def predicates(cls) -> dict[str, str]:
        out = {}
        for attr, fn in inspect.getmembers(cls, predicate=inspect.isfunction):
            if pname := getattr(fn, "__arbiter_predicate__", None):
                out[pname] = attr
        return out

    def tool_specs(self, *, descriptions: dict[str, str] | None = None, retrieval: bool = True) -> list[ToolSpec]:
        descriptions = descriptions or {}
        return [d.spec(descriptions.get(d.name)) for d in self.tool_defs() if retrieval or not d.retrieval]

    def call_tool(self, name: str, arguments: dict[str, Any], *, allowed: set[str] | None = None) -> ToolResult:
        defs = {d.name: d for d in self.tool_defs()}
        d = defs.get(name)
        if d is None or (allowed is not None and name not in allowed):
            return ToolResult(tool=name, ok=False, error_kind="unknown_tool",
                              error=f"unknown tool {name!r}; available: {', '.join(sorted(allowed or defs))}")
        for fault in self._faults:
            if fault.tool == name and fault.times > 0:
                fault.times -= 1
                return ToolResult(tool=name, ok=False, error_kind="fault", error=fault.error)
        try:
            args = d.args_model.model_validate(arguments)
        except ValidationError as exc:
            return ToolResult(tool=name, ok=False, error_kind="validation", error=_readable(exc))
        try:
            output = getattr(self, d.method_name)(args)
        except RuleViolation as exc:
            self.rule_events.append(RuleEvent(rule=exc.rule, tool=name, message=exc.message, arguments=arguments))
            return ToolResult(tool=name, ok=False, error_kind="rule", rule=exc.rule, error=exc.message)
        except ToolError as exc:
            return ToolResult(tool=name, ok=False, error_kind="tool_error", error=str(exc))
        if isinstance(output, BaseModel):
            output = output.model_dump(mode="json")
        return ToolResult(tool=name, ok=True, output=output, untrusted=d.untrusted_output)

    def request_approval(self, action: str, *, amount: float | None = None, reason: str = "",
                         payload: dict[str, Any] | None = None) -> Approval:
        approval = Approval(id=f"APR-{len(self.approvals) + 1}", action=action, amount=amount, reason=reason,
                            payload=payload or {})
        self.approvals.append(approval)
        return approval

    def system_context(self) -> str:
        """Facts the agent is allowed to know up front (current time, who it serves)."""
        return ""

    def policy_docs(self) -> list[PolicyDoc]:
        if self.fixtures_dir is None:
            return []
        pdir = Path(self.fixtures_dir) / "policies"
        if not pdir.exists():
            return []
        return [PolicyDoc(id=p.stem, title=p.stem.replace("_", " ").title(), text=p.read_text())
                for p in sorted(pdir.glob("*.md"))]

    def policy_search(self, query: str, k: int = 3) -> list[dict[str, str]]:
        if self._policy_index is None:
            self._policy_index = PolicyIndex(self.policy_docs())
        return self._policy_index.search(query, k)

    def sensitive_values(self) -> dict[str, set[str]]:
        """Map each data owner (e.g. customer id) to strings that must never reach another owner."""
        return {}

    def run_predicate(self, name: str, **kwargs: Any) -> tuple[bool, str]:
        attr = self.predicates().get(name)
        if attr is None:
            raise KeyError(f"{self.name} has no predicate {name!r}; known: {sorted(self.predicates())}")
        result = getattr(self, attr)(**kwargs)
        return result if isinstance(result, tuple) else (bool(result), "")


def _readable(exc: ValidationError) -> str:
    parts = []
    for err in exc.errors():
        loc = ".".join(str(x) for x in err["loc"]) or "arguments"
        parts.append(f"{loc}: {err['msg']}")
    return "invalid arguments - " + "; ".join(parts)
