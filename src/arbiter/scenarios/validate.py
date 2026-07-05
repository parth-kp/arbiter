from __future__ import annotations

from arbiter.checks.builtin import (
    ApprovalRequiredCheck,
    ArgConstraintCheck,
    CallOrderCheck,
    MustCallCheck,
    MustNotCallCheck,
    PredicateCheck,
)
from arbiter.core.environment import Environment
from arbiter.scenarios.spec import Scenario


def validate_scenario(s: Scenario, env_cls: type[Environment]) -> list[str]:
    """Static sanity checks that catch typos before money is spent running a scenario."""
    problems = []
    if s.environment != env_cls.name:
        problems.append(f"environment {s.environment!r} != {env_cls.name!r}")
    try:
        env_cls.from_state(env_cls.build_state(s.snapshot, s.patch))
    except Exception as exc:
        problems.append(f"snapshot does not build: {exc}")
    tools = {d.name for d in env_cls.tool_defs()}
    preds = env_cls.predicates()
    for c in s.checks:
        names = []
        if isinstance(c, MustCallCheck | MustNotCallCheck | ArgConstraintCheck | ApprovalRequiredCheck):
            names = [c.tool]
        elif isinstance(c, CallOrderCheck):
            names = c.tools
        for n in names:
            if n not in tools:
                problems.append(f"check {c.label()} references unknown tool {n!r}")
        if isinstance(c, PredicateCheck) and c.predicate not in preds:
            problems.append(f"unknown predicate {c.predicate!r}")
    for f in s.faults:
        if f.tool not in tools:
            problems.append(f"fault on unknown tool {f.tool!r}")
    if not any(c.kind in ("final_state",) for c in s.checks):
        problems.append("no final-state check (the primary signal)")
    return problems
