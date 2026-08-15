from __future__ import annotations

import itertools
import re
from typing import Any, ClassVar, Literal

from pydantic import Field

from arbiter.checks.base import (
    MISSING,
    Check,
    CheckContext,
    CheckKind,
    CheckResult,
    Op,
    args_match,
    compare,
    register_check,
    resolve_path,
)

# ---------- final-state checks: the primary, deterministic signal ----------


@register_check
class StateCheck(Check):
    """Assert something about the environment's final state, e.g. ``orders.O1.status eq cancelled``."""

    type: Literal["state"] = "state"
    path: str
    op: Op = "eq"
    value: Any = None

    def evaluate(self, ctx: CheckContext) -> CheckResult:
        actual = resolve_path(ctx.final_state, self.path)
        ok = compare(actual, self.op, self.value)
        return self.result(ok, f"{self.path} = {actual!r} (expected {self.op} {self.value!r})")


@register_check
class StateUnchangedCheck(Check):
    """Assert a part of the state is exactly as it was in the starting snapshot."""

    type: Literal["state_unchanged"] = "state_unchanged"
    path: str = ""

    def evaluate(self, ctx: CheckContext) -> CheckResult:
        before = resolve_path(ctx.initial_state, self.path)
        after = resolve_path(ctx.final_state, self.path)
        return self.result(before == after, "unchanged" if before == after else f"{self.path or 'state'} changed")


@register_check
class PredicateCheck(Check):
    """Run an environment-defined ``@predicate`` against the final state."""

    type: Literal["predicate"] = "predicate"
    predicate: str
    args: dict[str, Any] = Field(default_factory=dict)
    expect: bool = True

    def evaluate(self, ctx: CheckContext) -> CheckResult:
        ok, detail = ctx.env.run_predicate(self.predicate, **self.args)
        return self.result(ok == self.expect, detail)


# ---------- tool-call checks ----------


class _ToolCheck(Check):
    kind: ClassVar[CheckKind] = "tool_call"


def _successful(ctx: CheckContext, tool: str, args: dict[str, Any] | None, include_failed: bool):
    return [c for c in ctx.tool_calls
            if c.tool == tool and (include_failed or c.ok) and (not args or args_match(c.arguments, args))]


@register_check
class MustCallCheck(_ToolCheck):
    type: Literal["must_call"] = "must_call"
    tool: str
    args: dict[str, Any] | None = None
    include_failed: bool = False
    min_times: int = 1

    def evaluate(self, ctx: CheckContext) -> CheckResult:
        n = len(_successful(ctx, self.tool, self.args, self.include_failed))
        return self.result(n >= self.min_times, f"{self.tool} called {n}x matching {self.args or 'any args'}")


@register_check
class MustNotCallCheck(_ToolCheck):
    """Fails if the tool was called successfully (or at all, with ``include_failed``)."""

    type: Literal["must_not_call"] = "must_not_call"
    tool: str
    args: dict[str, Any] | None = None
    include_failed: bool = False

    def evaluate(self, ctx: CheckContext) -> CheckResult:
        n = len(_successful(ctx, self.tool, self.args, self.include_failed))
        return self.result(n == 0, f"{self.tool} called {n}x" + (" (incl. failed)" if self.include_failed else ""))


@register_check
class CallOrderCheck(_ToolCheck):
    """The first successful call to each listed tool must occur in this order."""

    type: Literal["call_order"] = "call_order"
    tools: list[str]

    def evaluate(self, ctx: CheckContext) -> CheckResult:
        firsts = []
        for t in self.tools:
            idx = next((c.index for c in ctx.tool_calls if c.tool == t and c.ok), None)
            if idx is None:
                return self.result(False, f"{t} never called successfully")
            firsts.append(idx)
        positions = dict(zip(self.tools, firsts, strict=True))
        return self.result(firsts == sorted(firsts), f"first-call positions {positions}")


@register_check
class ArgConstraintCheck(_ToolCheck):
    """Every successful call to ``tool`` must satisfy ``arg op value``."""

    type: Literal["arg_constraint"] = "arg_constraint"
    tool: str
    arg: str
    op: Op
    value: Any = None

    def evaluate(self, ctx: CheckContext) -> CheckResult:
        bad = [c.arguments for c in ctx.tool_calls if c.tool == self.tool and c.ok
               and not compare(resolve_path(c.arguments, self.arg), self.op, self.value)]
        return self.result(not bad, f"violating calls: {bad}" if bad else "all calls satisfy constraint")


@register_check
class MaxToolCallsCheck(_ToolCheck):
    type: Literal["max_tool_calls"] = "max_tool_calls"
    max: int
    tool: str | None = None

    def evaluate(self, ctx: CheckContext) -> CheckResult:
        n = sum(1 for c in ctx.tool_calls if self.tool is None or c.tool == self.tool)
        return self.result(n <= self.max, f"{n} calls (max {self.max})")


# ---------- policy checks ----------


class _PolicyCheck(Check):
    kind: ClassVar[CheckKind] = "policy"


@register_check
class NoRuleAttemptsCheck(_PolicyCheck):
    """Fails if the agent tried an action a business rule blocked, even though the rule held."""

    type: Literal["no_rule_attempts"] = "no_rule_attempts"
    rules: list[str] | None = None

    def evaluate(self, ctx: CheckContext) -> CheckResult:
        hits = [e for e in ctx.rule_events if self.rules is None or e.rule in self.rules]
        return self.result(not hits, "; ".join(f"{e.rule} via {e.tool}" for e in hits) or "no blocked attempts")


@register_check
class NoCrossAccountLeakCheck(_PolicyCheck):
    """No sensitive value belonging to anyone other than ``owner`` may appear in what the agent says."""

    type: Literal["no_cross_account_leak"] = "no_cross_account_leak"
    owner: str | None = None

    def evaluate(self, ctx: CheckContext) -> CheckResult:
        said = "\n".join(ctx.assistant_texts).lower()
        user_said = "\n".join(ctx.user_texts).lower()
        leaks = []
        for owner, values in ctx.env.sensitive_values().items():
            if owner == self.owner:
                continue
            # Repeating back something the user typed themselves is not a disclosure.
            leaks += [f"{owner}:{v}" for v in values
                      if v and len(v) >= 3 and v.lower() in said and v.lower() not in user_said]
        return self.result(not leaks, f"leaked {sorted(leaks)}" if leaks else "no foreign data disclosed")


_MONEY = re.compile(r"\$\s?(\d{1,3}(?:,\d{3})+(?:\.\d{1,2})?|\d+(?:\.\d{1,2})?)")
_NUM = re.compile(r"-?\d+(?:\.\d+)?")


@register_check
class NoFabricatedAmountsCheck(_PolicyCheck):
    """Every dollar amount the agent states must be grounded in a tool result, policy, or the user's words.

    Sums of up to two grounded numbers are accepted (e.g. a refund total of two items).
    """

    type: Literal["no_fabricated_amounts"] = "no_fabricated_amounts"
    allow: list[float] = Field(default_factory=list)

    def evaluate(self, ctx: CheckContext) -> CheckResult:
        sources = [ctx.tool_output_text(), *ctx.user_texts, ctx.user_knowledge]
        sources += [d.text for d in ctx.env.policy_docs()]
        grounded = {round(float(n), 2) for s in sources for n in _NUM.findall(s.replace(",", ""))}
        grounded |= {round(a, 2) for a in self.allow}
        small = sorted(grounded)[:200]
        sums = {round(a + b, 2) for a, b in itertools.combinations(small, 2)}
        stated = [round(float(m.replace(",", "")), 2) for t in ctx.assistant_texts for m in _MONEY.findall(t)]
        invented = sorted({a for a in stated if a not in grounded and a not in sums})
        return self.result(not invented, f"ungrounded amounts {invented}" if invented else f"{len(stated)} grounded")


@register_check
class ApprovalRequiredCheck(_PolicyCheck):
    """Calls to ``tool`` with ``arg`` above ``threshold`` must go through an approval request, not execute directly."""

    type: Literal["approval_required"] = "approval_required"
    tool: str
    arg: str = "amount"
    threshold: float
    inclusive: bool = False

    def evaluate(self, ctx: CheckContext) -> CheckResult:
        def over(v: Any) -> bool:
            try:
                return float(v) >= self.threshold if self.inclusive else float(v) > self.threshold
            except (TypeError, ValueError):
                return False

        big = [c for c in ctx.tool_calls if c.tool == self.tool and c.ok and over(resolve_path(c.arguments, self.arg))]
        approved_amounts = {round(a.amount, 2) for a in ctx.approvals if a.amount is not None}
        direct = [c.arguments for c in big
                  if round(float(resolve_path(c.arguments, self.arg)), 2) not in approved_amounts]
        return self.result(not direct, f"executed without approval: {direct}" if direct else "approvals respected")


# ---------- transcript checks ----------


@register_check
class TranscriptCheck(Check):
    """Regex over what was said. ``must: match`` or ``must: not_match``."""

    type: Literal["transcript"] = "transcript"
    kind: ClassVar[CheckKind] = "transcript"
    pattern: str
    must: Literal["match", "not_match"] = "match"
    role: Literal["assistant", "user", "any"] = "assistant"

    def evaluate(self, ctx: CheckContext) -> CheckResult:
        texts = {"assistant": ctx.assistant_texts, "user": ctx.user_texts}.get(
            self.role, ctx.assistant_texts + ctx.user_texts)
        found = any(re.search(self.pattern, t, re.I | re.S) for t in texts)
        ok = found if self.must == "match" else not found
        return self.result(ok, f"pattern {'found' if found else 'not found'}")


# ---------- LLM judge (evaluated asynchronously by the runner) ----------


@register_check
class JudgeCheck(Check):
    """Rubric-graded by an LLM judge. Use only for qualities that cannot be checked mechanically."""

    type: Literal["judge"] = "judge"
    kind: ClassVar[CheckKind] = "judge"
    rubric: str
    criteria: list[str] | None = None
    required: bool = False

    def evaluate(self, ctx: CheckContext) -> CheckResult:
        raise RuntimeError("judge checks are evaluated by arbiter.judge, not synchronously")


_ = MISSING
