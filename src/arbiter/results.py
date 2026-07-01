from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

from arbiter.checks.base import CheckResult
from arbiter.core.environment import Approval, RuleEvent
from arbiter.core.transcript import ToolCallRecord, TranscriptEvent
from arbiter.llm.types import CallRecord


class TrialResult(BaseModel):
    scenario_id: str
    category: str
    tags: list[str] = Field(default_factory=list)
    trial_index: int
    status: Literal["completed", "error"] = "completed"
    error: str | None = None
    termination: Literal["done", "give_up", "turn_limit", "error"] = "done"
    success: bool = False
    turns: int = 0
    checks: list[CheckResult] = Field(default_factory=list)
    events: list[TranscriptEvent] = Field(default_factory=list)
    tool_calls: list[ToolCallRecord] = Field(default_factory=list)
    rule_events: list[RuleEvent] = Field(default_factory=list)
    approvals: list[Approval] = Field(default_factory=list)
    state_diff: dict[str, Any] = Field(default_factory=dict)
    calls: list[CallRecord] = Field(default_factory=list)
    trace_id: str | None = None
    trace: list[dict[str, Any]] = Field(default_factory=list)

    @property
    def failed_checks(self) -> list[CheckResult]:
        return [c for c in self.checks if c.required and not c.passed]

    @property
    def policy_violation(self) -> bool:
        return any(c.kind == "policy" and not c.passed for c in self.checks)

    @property
    def policy_attempts(self) -> int:
        return len(self.rule_events)

    @property
    def tool_errors(self) -> int:
        return sum(1 for c in self.tool_calls if not c.ok and c.error_kind != "rule")

    def _agent_calls(self) -> list[CallRecord]:
        return [c for c in self.calls if c.purpose == "agent"]

    @property
    def cost_usd(self) -> float:
        """Cost of the agent under test for this conversation (as billed when recorded)."""
        return sum(c.cost_usd for c in self._agent_calls())

    @property
    def eval_cost_usd(self) -> float:
        """Cost of evaluation overhead: simulated user and judge."""
        return sum(c.cost_usd for c in self.calls if c.purpose != "agent")

    @property
    def latency_ms(self) -> float:
        return sum(c.latency_ms for c in self._agent_calls())

    @property
    def tokens(self) -> int:
        return sum(c.prompt_tokens + c.completion_tokens for c in self._agent_calls())


class RunResult(BaseModel):
    id: str
    created_at: str
    environment: str
    agent_type: str
    label: str = ""
    config: dict[str, Any]
    scenario_set: dict[str, Any]
    trials: list[TrialResult]
    summary: dict[str, Any] = Field(default_factory=dict)
    spend: dict[str, float] = Field(default_factory=dict)
    git_sha: str | None = None
    arbiter_version: str = ""
    aborted: str | None = None
