"""Statistics for eval runs.

Trials of one scenario are not independent samples of "the agent", so comparisons are paired by scenario and
uncertainty for scenario-level metrics is bootstrapped over scenarios, not over trials.
"""

from __future__ import annotations

import math
import random
from collections import defaultdict
from collections.abc import Callable, Iterable, Sequence
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from arbiter.results import RunResult, TrialResult

Z95 = 1.959963984540054


def wilson(successes: int, n: int, z: float = Z95) -> tuple[float, float]:
    if n == 0:
        return (0.0, 0.0)
    p = successes / n
    denom = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / denom
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / denom
    return (max(0.0, centre - half), min(1.0, centre + half))


def pass_at_k(n: int, c: int, k: int) -> float:
    """Unbiased P(at least one of k sampled trials succeeds), given c successes in n trials (Chen et al. 2021)."""
    if k > n:
        raise ValueError("k cannot exceed n")
    if n - c < k:
        return 1.0
    return 1.0 - math.comb(n - c, k) / math.comb(n, k)


def pass_hat_k(n: int, c: int, k: int) -> float:
    """Unbiased P(all k sampled trials succeed): C(c,k)/C(n,k) (the tau-bench pass^k)."""
    if k > n:
        raise ValueError("k cannot exceed n")
    return math.comb(c, k) / math.comb(n, k)


def percentile(values: Sequence[float], q: float) -> float:
    if not values:
        return 0.0
    xs = sorted(values)
    pos = (len(xs) - 1) * q
    lo, hi = math.floor(pos), math.ceil(pos)
    return xs[lo] + (xs[hi] - xs[lo]) * (pos - lo)


def bootstrap_ci(values: Sequence[float], stat: Callable[[Sequence[float]], float] = None, *, n_boot: int = 2000,
                 seed: int = 0, alpha: float = 0.05) -> tuple[float, float]:
    stat = stat or (lambda xs: sum(xs) / len(xs))
    if not values:
        return (0.0, 0.0)
    rng = random.Random(seed)
    vals = list(values)
    boots = sorted(stat([rng.choice(vals) for _ in vals]) for _ in range(n_boot))
    return (boots[int(alpha / 2 * n_boot)], boots[int((1 - alpha / 2) * n_boot) - 1])


def paired_permutation_test(diffs: Sequence[float], *, n_perm: int = 20000, seed: int = 0) -> float:
    """Two-sided sign-flip test on per-scenario differences. Exact when there are <= 16 non-zero diffs."""
    d = [x for x in diffs if abs(x) > 1e-12]
    if not d:
        return 1.0
    observed = abs(sum(d))
    if len(d) <= 16:
        hits = total = 0
        for mask in range(1 << len(d)):
            s = sum(x if (mask >> i) & 1 else -x for i, x in enumerate(d))
            hits += abs(s) >= observed - 1e-12
            total += 1
        return hits / total
    rng = random.Random(seed)
    hits = sum(abs(sum(x if rng.random() < 0.5 else -x for x in d)) >= observed - 1e-12 for _ in range(n_perm))
    return (hits + 1) / (n_perm + 1)


def _by_scenario(trials: Iterable[TrialResult]) -> dict[str, list[TrialResult]]:
    out: dict[str, list[TrialResult]] = defaultdict(list)
    for t in trials:
        out[t.scenario_id].append(t)
    return out


def _metrics(trials: list[TrialResult], k: int) -> dict[str, Any]:
    n = len(trials)
    if n == 0:
        return {"n_trials": 0}
    succ = sum(t.success for t in trials)
    groups = _by_scenario(trials)
    kk = max(1, min(k, min(len(v) for v in groups.values())))
    pak = [pass_at_k(len(v), sum(t.success for t in v), kk) for v in groups.values()]
    phk = [pass_hat_k(len(v), sum(t.success for t in v), kk) for v in groups.values()]
    viol = sum(t.policy_violation for t in trials)
    attempts = sum(t.policy_attempts > 0 for t in trials)
    n_tool = sum(len(t.tool_calls) for t in trials)
    n_tool_err = sum(t.tool_errors for t in trials)
    completed = [t for t in trials if t.status == "completed"]
    lat = [t.latency_ms for t in completed]
    cost = sum(t.cost_usd for t in trials)
    return {
        "n_scenarios": len(groups),
        "n_trials": n,
        "k": kk,
        "success_rate": succ / n,
        "success_ci95": wilson(succ, n),
        f"pass@{kk}": sum(pak) / len(pak),
        f"pass@{kk}_ci95": bootstrap_ci(pak),
        f"pass^{kk}": sum(phk) / len(phk),
        f"pass^{kk}_ci95": bootstrap_ci(phk),
        "policy_violation_rate": viol / n,
        "policy_violation_ci95": wilson(viol, n),
        "policy_attempt_rate": attempts / n,
        "policy_attempt_ci95": wilson(attempts, n),
        "tool_error_rate": (n_tool_err / n_tool) if n_tool else 0.0,
        "error_rate": sum(t.status == "error" for t in trials) / n,
        "avg_turns": sum(t.turns for t in trials) / n,
        "latency_p50_ms": percentile(lat, 0.5),
        "latency_p95_ms": percentile(lat, 0.95),
        "avg_tokens": sum(t.tokens for t in trials) / n,
        "cost_per_conversation_usd": cost / n,
        "cost_per_success_usd": (cost / succ) if succ else None,
        "total_agent_cost_usd": cost,
    }


def summarize(run: RunResult, k: int | None = None) -> dict[str, Any]:
    k = k or run.config.get("trials", 1)
    trials = run.trials
    by_cat: dict[str, list[TrialResult]] = defaultdict(list)
    for t in trials:
        by_cat[t.category].append(t)
    return {"overall": _metrics(trials, k), "by_category": {c: _metrics(v, k) for c, v in sorted(by_cat.items())}}


def scenario_rates(trials: Iterable[TrialResult], metric: str = "success") -> dict[str, float]:
    get = {
        "success": lambda t: float(t.success),
        "violation": lambda t: float(t.policy_violation),
        "attempt": lambda t: float(t.policy_attempts > 0),
    }[metric]
    return {sid: sum(get(t) for t in ts) / len(ts) for sid, ts in _by_scenario(trials).items()}


def compare_runs(a: RunResult, b: RunResult, *, metrics: tuple[str, ...] = ("success", "violation", "attempt"),
                 alpha: float = 0.05) -> dict[str, Any]:
    """Compare run B against baseline A on the scenarios both ran, paired by scenario."""
    out: dict[str, Any] = {"baseline": a.id, "candidate": b.id, "alpha": alpha, "metrics": {}, "by_category": {}}
    cats = {t.scenario_id: t.category for t in a.trials + b.trials}
    for metric in metrics:
        ra, rb = scenario_rates(a.trials, metric), scenario_rates(b.trials, metric)
        common = sorted(set(ra) & set(rb))
        out["metrics"][metric] = _paired(ra, rb, common, alpha)
        for cat in sorted({cats[s] for s in common}):
            ids = [s for s in common if cats[s] == cat]
            out["by_category"].setdefault(cat, {})[metric] = _paired(ra, rb, ids, alpha)
    ra, rb = scenario_rates(a.trials), scenario_rates(b.trials)
    common = sorted(set(ra) & set(rb))
    out["newly_failing"] = [s for s in common if ra[s] >= 0.5 > rb[s]]
    out["newly_passing"] = [s for s in common if rb[s] >= 0.5 > ra[s]]
    out["only_in_baseline"] = sorted(set(ra) - set(rb))
    out["only_in_candidate"] = sorted(set(rb) - set(ra))
    return out


def _paired(ra: dict[str, float], rb: dict[str, float], ids: list[str], alpha: float) -> dict[str, Any]:
    if not ids:
        return {"n": 0}
    diffs = [rb[s] - ra[s] for s in ids]
    p = paired_permutation_test(diffs)
    mean_a = sum(ra[s] for s in ids) / len(ids)
    mean_b = sum(rb[s] for s in ids) / len(ids)
    return {"n": len(ids), "baseline": mean_a, "candidate": mean_b, "delta": mean_b - mean_a,
            "delta_ci95": bootstrap_ci(diffs), "p_value": p, "significant": p < alpha}
