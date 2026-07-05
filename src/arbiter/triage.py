from __future__ import annotations

from collections import defaultdict
from typing import Any

from arbiter.results import RunResult, TrialResult

KIND_PRIORITY = {"policy": 0, "final_state": 1, "tool_call": 2, "transcript": 3, "judge": 4}


def failure_reason(t: TrialResult) -> str:
    """One stable label per failed trial: the most important failed check (errors trump everything)."""
    if t.status == "error":
        err = (t.error or "error").split(":")[0]
        return f"error:{err}"
    failed = sorted(t.failed_checks, key=lambda c: (KIND_PRIORITY.get(c.kind, 9), c.name))
    if not failed:
        return "unknown"
    return f"{failed[0].kind}:{failed[0].name}"


def _excerpt(t: TrialResult, limit: int = 6) -> list[dict[str, Any]]:
    out = []
    for e in t.events:
        if e.kind in ("user", "assistant", "error"):
            out.append({"role": e.kind, "text": (e.content or "")[:400]})
        elif e.kind == "tool_result" and not e.ok:
            out.append({"role": "tool", "text": f"{e.tool} -> {e.error_kind}: {str(e.result)[:200]}"})
        elif e.kind == "tool_call":
            out.append({"role": "tool_call", "text": f"{e.tool}({e.arguments})"[:300]})
    return out[-limit:]


def triage(run: RunResult, top: int = 10, examples: int = 2) -> list[dict[str, Any]]:
    groups: dict[str, list[TrialResult]] = defaultdict(list)
    for t in run.trials:
        if not t.success:
            groups[failure_reason(t)].append(t)
    failed_total = sum(len(v) for v in groups.values())
    patterns = []
    for reason, ts in sorted(groups.items(), key=lambda kv: (-len(kv[1]), kv[0])):
        details = defaultdict(int)
        for t in ts:
            for c in t.failed_checks:
                if f"{c.kind}:{c.name}" == reason:
                    details[c.detail[:120]] += 1
        patterns.append({
            "reason": reason,
            "count": len(ts),
            "share": len(ts) / failed_total if failed_total else 0.0,
            "scenarios": sorted({t.scenario_id for t in ts}),
            "categories": sorted({t.category for t in ts}),
            "top_details": sorted(details.items(), key=lambda kv: -kv[1])[:3],
            "examples": [{"run_id": run.id, "scenario_id": t.scenario_id, "trial_index": t.trial_index,
                          "trace_id": t.trace_id, "excerpt": _excerpt(t)} for t in ts[:examples]],
        })
    return patterns[:top]
