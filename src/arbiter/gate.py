from __future__ import annotations

from typing import Any

from pydantic import BaseModel

from arbiter.results import RunResult
from arbiter.stats import compare_runs


class GatePolicy(BaseModel):
    alpha: float = 0.05
    max_success_drop: float = 0.05
    max_violation_rise: float = 0.0
    max_attempt_rise: float = 0.05
    max_error_rate: float = 0.0


def gate(baseline: RunResult, candidate: RunResult, policy: GatePolicy | None = None) -> dict[str, Any]:
    """Fail on a statistically significant drop in success or rise in policy violations/attempts.

    A change must be both significant (paired permutation test) and larger than the tolerance, so a noisy
    one-scenario wobble does not block a merge and a real regression cannot hide behind a small n.
    """
    policy = policy or GatePolicy()
    cmp = compare_runs(baseline, candidate, alpha=policy.alpha)
    reasons: list[str] = []
    s = cmp["metrics"]["success"]
    if s.get("n") and s["significant"] and s["delta"] < -policy.max_success_drop:
        reasons.append(f"success dropped {s['baseline']:.1%} -> {s['candidate']:.1%} (p={s['p_value']:.3f})")
    for metric, tol in (("violation", policy.max_violation_rise), ("attempt", policy.max_attempt_rise)):
        m = cmp["metrics"][metric]
        if m.get("n") and m["significant"] and m["delta"] > tol:
            reasons.append(f"policy {metric} rate rose {m['baseline']:.1%} -> {m['candidate']:.1%} "
                           f"(p={m['p_value']:.3f})")
    errors = sum(t.status == "error" for t in candidate.trials) / max(1, len(candidate.trials))
    if errors > policy.max_error_rate:
        reasons.append(f"{errors:.1%} of candidate trials errored (e.g. replay drift or crashes)")
    if cmp["only_in_baseline"]:
        reasons.append(f"candidate is missing {len(cmp['only_in_baseline'])} baseline scenarios")
    return {"passed": not reasons, "reasons": reasons, "comparison": cmp, "policy": policy.model_dump()}
