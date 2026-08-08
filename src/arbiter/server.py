"""Dashboard API. Serves the built React app from dashboard/web/dist when present."""

from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from arbiter import calibration
from arbiter.judge import load_rubric
from arbiter.stats import compare_runs
from arbiter.store import Store, import_runs
from arbiter.tracing import trace_url
from arbiter.triage import triage


class LabelIn(BaseModel):
    item_id: str
    criterion: str
    verdict: str


class DecisionIn(BaseModel):
    decision: str
    by: str = "reviewer"
    note: str = ""


def _run_row(r: dict[str, Any]) -> dict[str, Any]:
    o = (r.get("summary") or {}).get("overall", {})
    cfg = r.get("config") or {}
    agent = cfg.get("agent", {})
    k = o.get("k", 1)
    return {
        "id": r["id"], "created_at": r["created_at"], "environment": r["environment"], "label": r.get("label", ""),
        "agent_type": r["agent_type"], "model": agent.get("model"), "prompt_version": agent.get("prompt_version"),
        "tool_descriptions": agent.get("tool_descriptions"), "retrieval": agent.get("retrieval"),
        "injection_defense": agent.get("injection_defense"), "temperature": agent.get("temperature"),
        "trials_per_scenario": cfg.get("trials"), "scenario_set": r["scenario_set"],
        "n_trials": o.get("n_trials"), "success_rate": o.get("success_rate"), "success_ci95": o.get("success_ci95"),
        "pass_hat_k": o.get(f"pass^{k}"), "k": k, "violation_rate": o.get("policy_violation_rate"),
        "attempt_rate": o.get("policy_attempt_rate"), "cost_per_conversation": o.get("cost_per_conversation_usd"),
        "cost_per_success": o.get("cost_per_success_usd"), "spend": r.get("spend"), "git_sha": r.get("git_sha"),
    }


def create_app(db: str | None = None, results_dir: str = "results/runs", rubrics_dir: str = "rubrics",
               labels_dir: str = "labels", static_dir: str | None = "dashboard/web/dist") -> FastAPI:
    store = Store(db)
    if Path(results_dir).exists():
        import_runs(store, results_dir)
    labels_path = Path(labels_dir)
    app = FastAPI(title="Arbiter", version="0.1.0")

    def run_or_404(run_id: str):
        run = store.get_run(run_id)
        if run is None:
            raise HTTPException(404, f"run {run_id} not found")
        return run

    @app.get("/api/runs")
    def runs() -> list[dict[str, Any]]:
        return [_run_row(r) for r in store.list_runs()]

    @app.get("/api/runs/{run_id}")
    def run_detail(run_id: str) -> dict[str, Any]:
        run = run_or_404(run_id)
        per: dict[str, dict[str, Any]] = defaultdict(lambda: {"trials": 0, "successes": 0, "violations": 0})
        for t in run.trials:
            p = per[t.scenario_id]
            p.update(scenario_id=t.scenario_id, category=t.category)
            p["trials"] += 1
            p["successes"] += t.success
            p["violations"] += t.policy_violation
            p.setdefault("failed_checks", set()).update(c.name for c in t.failed_checks)
        scenarios = [{**v, "failed_checks": sorted(v.get("failed_checks", []))} for v in per.values()]
        return {"run": _run_row(store.list_runs_by_id(run_id)), "config": run.config, "summary": run.summary,
                "scenarios": sorted(scenarios, key=lambda s: s["scenario_id"]), "aborted": run.aborted}

    @app.get("/api/runs/{run_id}/scenarios/{scenario_id}")
    def scenario_detail(run_id: str, scenario_id: str) -> dict[str, Any]:
        trials = store.scenario_trials(run_id, scenario_id)
        if not trials:
            raise HTTPException(404, "no trials for that scenario in this run")
        for t in trials:
            t["trace_url"] = trace_url(t["trace_id"]) if t.get("trace_id") else None
        return {"run_id": run_id, "scenario_id": scenario_id, "trials": trials}

    @app.get("/api/runs/{run_id}/failures")
    def failures(run_id: str) -> list[dict[str, Any]]:
        return triage(run_or_404(run_id), top=15, examples=3)

    @app.get("/api/compare")
    def compare(a: str, b: str) -> dict[str, Any]:
        ra, rb = run_or_404(a), run_or_404(b)
        return {"a": _run_row(store.list_runs_by_id(a)), "b": _run_row(store.list_runs_by_id(b)),
                "config_a": ra.config, "config_b": rb.config, "comparison": compare_runs(ra, rb)}

    @app.get("/api/traces/{trace_id}")
    def trace(trace_id: str) -> dict[str, Any]:
        found = store.trial_by_trace(trace_id)
        if not found:
            raise HTTPException(404, "trace not found")
        t = found["trial"]
        return {"trace_id": trace_id, "run_id": found["run_id"], "scenario_id": t["scenario_id"],
                "trial_index": t["trial_index"], "spans": t.get("trace", [])}

    @app.get("/api/labels/items")
    def label_items() -> dict[str, Any]:
        items = calibration.load_items(labels_path / "items.json")
        human = calibration.load_human_labels(labels_path / "human_labels.json")
        rubric = load_rubric("assistant_quality", rubrics_dir)
        return {"rubric": rubric.model_dump(), "labels": human,
                "items": [{k: v for k, v in i.items() if k != "events"} for i in items]}

    @app.post("/api/labels")
    def save_label(body: LabelIn) -> dict[str, Any]:
        ids = {i["item_id"] for i in calibration.load_items(labels_path / "items.json")}
        if body.item_id not in ids:
            raise HTTPException(404, "unknown item")
        try:
            calibration.save_human_label(body.item_id, body.criterion, body.verdict, labels_path / "human_labels.json")
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc
        return {"ok": True}

    @app.get("/api/calibration")
    def calibration_report() -> list[dict[str, Any]]:
        out = []
        for p in sorted(Path("results/calibration").glob("*.json")):
            if not p.name.endswith("-judge-verdicts.json"):
                out.append(json.loads(p.read_text()))
        return out

    @app.get("/api/approvals")
    def approvals(status: str | None = None) -> list[dict[str, Any]]:
        return store.approvals(status)

    @app.post("/api/approvals/{pk}")
    def decide(pk: int, body: DecisionIn) -> dict[str, Any]:
        try:
            ok = store.decide_approval(pk, body.decision, body.by, body.note)
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc
        if not ok:
            raise HTTPException(409, "approval not found or already decided")
        return {"ok": True}

    if static_dir and Path(static_dir).exists():
        app.mount("/assets", StaticFiles(directory=Path(static_dir) / "assets"), name="assets")

        @app.get("/{path:path}")
        def spa(path: str) -> FileResponse:
            return FileResponse(Path(static_dir) / "index.html")

    return app
