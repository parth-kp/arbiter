"""Render experiment tables from committed run JSON, so documentation numbers are never typed by hand."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from arbiter.results import RunResult
from arbiter.stats import compare_runs, summarize
from arbiter.store import read_run_json


def _pct(x: float | None) -> str:
    return "–" if x is None else f"{x * 100:.1f}%"


def _ci(ci: list[float] | None) -> str:
    return "" if not ci else f" [{ci[0] * 100:.0f}–{ci[1] * 100:.0f}]"


def _usd(x: float | None) -> str:
    if x is None:
        return "–"
    return f"${x:.4f}" if x < 0.01 else f"${x:.3f}"


def complete_scenarios(runs: list[RunResult]) -> set[str]:
    """Scenarios whose every trial completed in every run, for comparing arms when one was cut short."""
    ids = None
    for run in runs:
        bad = {t.scenario_id for t in run.trials if t.status != "completed"}
        have = {t.scenario_id for t in run.trials} - bad
        ids = have if ids is None else ids & have
    return ids or set()


def _filter(run: RunResult, categories: list[str] | None, scenarios: set[str] | None = None) -> RunResult:
    if not categories and scenarios is None:
        return run
    sub = run.model_copy(update={"trials": [t for t in run.trials if (not categories or t.category in categories)
                                            and (scenarios is None or t.scenario_id in scenarios)]})
    sub.summary = summarize(sub, k=run.config.get("trials", 1))
    return sub


def metrics_table(rows: list[tuple[str, RunResult]], link_root: str) -> str:
    head = ("| Arm | Run | n | Success [95% CI] | pass^k | Violations | Blocked attempts | Tool errors | "
            "p50 / p95 latency | $/conversation | $/success |\n|---|---|---|---|---|---|---|---|---|---|---|")
    out = [head]
    for name, run in rows:
        o = run.summary["overall"]
        k = o["k"]
        out.append(
            f"| {name} | [{run.id}]({link_root}/{run.id}.json) | {o['n_trials']} | {_pct(o['success_rate'])}"
            f"{_ci(o['success_ci95'])} | {_pct(o[f'pass^{k}'])} (k={k}) | {_pct(o['policy_violation_rate'])} | "
            f"{_pct(o['policy_attempt_rate'])} | {_pct(o['tool_error_rate'])} | "
            f"{o['latency_p50_ms'] / 1000:.1f}s / {o['latency_p95_ms'] / 1000:.1f}s | "
            f"{_usd(o['cost_per_conversation_usd'])} | {_usd(o['cost_per_success_usd'])} |")
    return "\n".join(out)


def comparison_table(base: RunResult, cand: RunResult) -> str:
    cmp = compare_runs(base, cand)
    out = ["| Scope | Metric | Baseline | Candidate | Δ | p | |", "|---|---|---|---|---|---|---|"]
    scopes = [("all", cmp["metrics"])] + sorted(cmp["by_category"].items())
    for scope, metrics in scopes:
        for metric, m in metrics.items():
            if not m.get("n") or (scope != "all" and metric != "success"):
                continue
            mark = "**significant**" if m["significant"] else ""
            out.append(f"| {scope} | {metric} | {_pct(m['baseline'])} | {_pct(m['candidate'])} | "
                       f"{m['delta'] * 100:+.1f} pp | {m['p_value']:.3f} | {mark} |")
    nf, np_ = cmp["newly_failing"], cmp["newly_passing"]
    out.append("")
    out.append(f"Newly passing ({len(np_)}): {', '.join(f'`{s}`' for s in np_) or 'none'}  ")
    out.append(f"Newly failing ({len(nf)}): {', '.join(f'`{s}`' for s in nf) or 'none'}")
    return "\n".join(out)


def render(spec_path: str | Path, results_dir: str = "results/runs", link_root: str = "../results/runs") -> str:
    spec = yaml.safe_load(Path(spec_path).read_text())
    parts: list[str] = []
    for exp in spec["experiments"]:
        parts.append(f"### {exp['title']}\n")
        if exp.get("note"):
            parts.append(exp["note"].strip() + "\n")
        for env, arms in exp["environments"].items():
            raw = [(arm["name"], read_run_json(Path(results_dir) / f"{arm['run']}.json")) for arm in arms]
            keep = None
            if exp.get("complete_scenarios_only"):
                keep = complete_scenarios([r for _, r in raw])
            loaded = [(name, _filter(run, exp.get("categories"), keep)) for name, run in raw]
            note = f" (categories: {', '.join(exp['categories'])})" if exp.get("categories") else ""
            if keep is not None:
                total = len({t.scenario_id for _, r in raw for t in r.trials})
                note += (f" (only the {len(keep)} of {total} scenarios where every trial completed in every arm; "
                         f"the others were cut short by a run budget cap)")
            parts.append(f"**{env}**{note}\n")
            parts.append(metrics_table(loaded, link_root) + "\n")
            for a, b in exp.get("compare", []):
                names = dict(loaded)
                if a in names and b in names:
                    parts.append(f"*{b} vs {a}* (paired by scenario, two-sided permutation test):\n")
                    parts.append(comparison_table(names[a], names[b]) + "\n")
    return "\n".join(parts)


def total_spend(ledger: dict[str, Any]) -> float:
    return float(ledger.get("total_usd", 0.0))
