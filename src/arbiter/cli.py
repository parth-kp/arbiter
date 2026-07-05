from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path
from typing import Annotated

import typer
from rich.console import Console
from rich.table import Table

app = typer.Typer(help="Arbiter: evaluate tool-using AI agents.", no_args_is_help=True, add_completion=False)
env_app = typer.Typer(help="Inspect environments.", no_args_is_help=True)
scen_app = typer.Typer(help="Work with scenarios.", no_args_is_help=True)
app.add_typer(env_app, name="env")
app.add_typer(scen_app, name="scenarios")
console = Console()


def load_dotenv(path: str = ".env") -> None:
    p = Path(path)
    if not p.exists():
        return
    for line in p.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


def _pct(x) -> str:
    return "-" if x is None else f"{x:.1%}"


def _ci(ci) -> str:
    return f"[{ci[0]:.0%}, {ci[1]:.0%}]" if ci else ""


def print_summary(summary: dict, title: str) -> None:
    t = Table(title=title)
    for col in ("category", "n", "success", "95% CI", "pass^k", "violations", "attempts", "tool err", "turns",
                "p50 ms", "p95 ms", "$/conv", "$/success"):
        t.add_column(col, justify="right" if col != "category" else "left")
    rows = [("ALL", summary["overall"])] + list(summary["by_category"].items())
    for name, m in rows:
        if not m.get("n_trials"):
            continue
        k = m["k"]
        cps = m["cost_per_success_usd"]
        t.add_row(name, str(m["n_trials"]), _pct(m["success_rate"]), _ci(m["success_ci95"]), _pct(m[f"pass^{k}"]),
                  _pct(m["policy_violation_rate"]), _pct(m["policy_attempt_rate"]), _pct(m["tool_error_rate"]),
                  f"{m['avg_turns']:.1f}", f"{m['latency_p50_ms']:.0f}", f"{m['latency_p95_ms']:.0f}",
                  f"{m['cost_per_conversation_usd']:.4f}", "-" if cps is None else f"{cps:.4f}")
    console.print(t)


@env_app.command("list")
def env_list() -> None:
    """List registered environments and their tools."""
    from arbiter.core.registry import list_environments

    t = Table(title="Environments")
    for c in ("name", "description", "tools"):
        t.add_column(c)
    for name, cls in sorted(list_environments().items()):
        t.add_row(name, cls.description, ", ".join(d.name for d in cls.tool_defs()))
    console.print(t)


@app.command()
def run(
    env: Annotated[str, typer.Option("--env", help="Environment name or module:Class")],
    agent: Annotated[str | None, typer.Option(help="reference | openai | http | langgraph | module:Class")] = None,
    config: Annotated[str | None, typer.Option(help="Run config YAML")] = None,
    set_: Annotated[str | None, typer.Option("--set", help="golden | all | category:X | tag:X | set file")] = None,
    trials: Annotated[int | None, typer.Option(help="Trials per scenario (k)")] = None,
    mode: Annotated[str | None, typer.Option(help="live | record | replay | cache")] = None,
    model: Annotated[str | None, typer.Option(help="Override agent model")] = None,
    prompt_version: Annotated[str | None, typer.Option(help="Override agent prompt version")] = None,
    limit: Annotated[int | None, typer.Option(help="Only the first N scenarios of the set")] = None,
    category: Annotated[list[str] | None, typer.Option(help="Restrict to these categories")] = None,
    label: Annotated[str | None, typer.Option(help="Free-text label stored with the run")] = None,
    name: Annotated[str | None, typer.Option(help="Run name (also names the cassette)")] = None,
    cassette: Annotated[str | None, typer.Option(help="Cassette path override")] = None,
    budget: Annotated[float | None, typer.Option(help="Per-run budget cap in USD")] = None,
    no_judge: Annotated[bool, typer.Option("--no-judge", help="Skip LLM-judge checks")] = False,
    no_db: Annotated[bool, typer.Option("--no-db", help="Only write JSON, skip the database")] = False,
    out: Annotated[str | None, typer.Option(help="Results directory override")] = None,
) -> None:
    """Run an evaluation and save results as JSON (and to the database)."""
    from arbiter.runner.service import execute_run

    load_dotenv()
    overrides = {"agent.type": agent, "set": set_, "trials": trials, "mode": mode, "agent.model": model,
                 "agent.prompt_version": prompt_version, "limit": limit, "categories": category, "label": label,
                 "name": name, "cassette": cassette, "budget_usd": budget, "results_dir": out}
    if no_judge:
        overrides["judge.enabled"] = False
    result, path = asyncio.run(execute_run(env, config, overrides, save_db=not no_db))
    print_summary(result.summary, f"{result.id}  ({result.environment}, {result.agent_type})")
    console.print(f"spend: live ${result.spend['live_usd']:.4f} | results: {path}")
    if result.aborted:
        console.print(f"[red]run aborted: {result.aborted}[/red]")
        raise typer.Exit(2)


@app.command()
def compare(run_a: str, run_b: str, results_dir: str = "results/runs",
            as_json: Annotated[bool, typer.Option("--json")] = False) -> None:
    """Compare run B against baseline run A, paired by scenario, with significance tests."""
    from arbiter.stats import compare_runs
    from arbiter.store import resolve_run

    a, b = resolve_run(run_a, results_dir), resolve_run(run_b, results_dir)
    cmp = compare_runs(a, b)
    if as_json:
        console.print_json(json.dumps(cmp))
        return
    t = Table(title=f"{b.id} vs baseline {a.id}")
    for c in ("scope", "metric", "baseline", "candidate", "delta", "p", "sig"):
        t.add_column(c)
    scopes = [("ALL", cmp["metrics"])] + list(cmp["by_category"].items())
    for scope, metrics in scopes:
        for metric, m in metrics.items():
            if not m.get("n"):
                continue
            t.add_row(scope, metric, _pct(m["baseline"]), _pct(m["candidate"]), f"{m['delta']:+.1%}",
                      f"{m['p_value']:.3f}", "*" if m["significant"] else "")
    console.print(t)
    console.print(f"newly failing: {cmp['newly_failing'] or 'none'}")
    console.print(f"newly passing: {cmp['newly_passing'] or 'none'}")


@app.command("gate")
def gate_cmd(
    run_ref: Annotated[str | None, typer.Argument(help="Candidate run (path, id or prefix)")] = None,
    baseline: Annotated[str, typer.Option(help="Baseline run JSON")] = "baselines/store.json",
    results_dir: str = "results/runs",
    alpha: float = 0.05,
    max_success_drop: float = 0.05,
) -> None:
    """Fail (exit 1) if the candidate run significantly regresses against the committed baseline."""
    from arbiter.gate import GatePolicy, gate
    from arbiter.store import read_run_json, resolve_run

    if run_ref is None:
        runs = sorted(Path(results_dir).glob("*.json"), key=lambda p: p.stat().st_mtime)
        if not runs:
            raise typer.BadParameter("no runs found; pass a run")
        run_ref = str(runs[-1])
    cand = resolve_run(run_ref, results_dir)
    base = read_run_json(baseline)
    res = gate(base, cand, GatePolicy(alpha=alpha, max_success_drop=max_success_drop))
    s = res["comparison"]["metrics"]["success"]
    console.print(f"baseline {base.id}: success {_pct(s.get('baseline'))} | candidate {cand.id}: "
                  f"{_pct(s.get('candidate'))} (p={s.get('p_value', 1):.3f})")
    if res["passed"]:
        console.print("[green]GATE PASSED[/green]")
        return
    for r in res["reasons"]:
        console.print(f"[red]- {r}[/red]")
    console.print("[red]GATE FAILED[/red]")
    raise typer.Exit(1)


@app.command()
def triage(run_ref: str, results_dir: str = "results/runs", top: int = 8) -> None:
    """Show the top failure patterns of a run with example transcripts."""
    from arbiter.store import resolve_run
    from arbiter.triage import triage as do_triage

    run_ = resolve_run(run_ref, results_dir)
    for p in do_triage(run_, top=top):
        console.rule(f"{p['reason']}  x{p['count']} ({p['share']:.0%} of failures)")
        console.print(f"scenarios: {', '.join(p['scenarios'][:8])}")
        for d, n in p["top_details"]:
            console.print(f"  {n}x {d}")
        ex = p["examples"][0]
        console.print(f"  example {ex['scenario_id']}#{ex['trial_index']} trace {ex['trace_id']}")
        for line in ex["excerpt"]:
            console.print(f"    [dim]{line['role']}:[/dim] {line['text'][:160]}")


@app.command()
def spend(ledger: str = "results/spend_ledger.json") -> None:
    """Show total live spend recorded in the ledger."""
    data = json.loads(Path(ledger).read_text())
    t = Table(title=f"Live spend: ${data['total_usd']:.4f} of ${data['cap_usd']:.2f} cap")
    for c in ("run", "calls", "cost", "providers"):
        t.add_column(c)
    for rid, r in sorted(data["runs"].items(), key=lambda kv: kv[1].get("started", "")):
        t.add_row(rid, str(r["calls"]), f"${r['cost_usd']:.4f}", json.dumps(r["by_provider"]))
    console.print(t)


@app.command("import")
def import_cmd(results_dir: str = "results/runs", db: str | None = None) -> None:
    """Load committed run JSON files into the database (for the dashboard)."""
    from arbiter.store import Store, import_runs

    n = import_runs(Store(db), results_dir)
    console.print(f"imported {n} runs")


@scen_app.command("list")
def scenarios_list(env: str, root: str = "scenarios") -> None:
    """Count scenarios by category for an environment."""
    from collections import Counter

    from arbiter.scenarios import load_scenarios

    sc = load_scenarios(Path(root) / env)
    cats = Counter(s.category for s in sc)
    t = Table(title=f"{env}: {len(sc)} scenarios, {sum(s.golden for s in sc)} golden")
    t.add_column("category")
    t.add_column("count", justify="right")
    t.add_column("golden", justify="right")
    for c, n in sorted(cats.items()):
        t.add_row(c, str(n), str(sum(1 for s in sc if s.category == c and s.golden)))
    console.print(t)


@scen_app.command("validate")
def scenarios_validate(env: str, root: str = "scenarios") -> None:
    """Load every scenario, build its snapshot and check that referenced tools and predicates exist."""
    from arbiter.core.registry import get_environment
    from arbiter.scenarios import load_scenarios
    from arbiter.scenarios.validate import validate_scenario

    cls = get_environment(env)
    problems = []
    sc = load_scenarios(Path(root) / env)
    for s in sc:
        problems += [f"{s.id}: {p}" for p in validate_scenario(s, cls)]
    for p in problems:
        console.print(f"[red]{p}[/red]")
    console.print(f"{len(sc)} scenarios, {len(problems)} problems")
    if problems:
        raise typer.Exit(1)


if __name__ == "__main__":
    app()
