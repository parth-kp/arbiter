"""Results store. JSON files under results/runs are the committed source of truth; the database is an index
for the dashboard and the approval/labelling workflows. SQLite by default, PostgreSQL via ARBITER_DATABASE_URL."""

from __future__ import annotations

import json
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sqlalchemy import (
    JSON,
    Boolean,
    Column,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    MetaData,
    String,
    Table,
    Text,
    create_engine,
    delete,
    insert,
    select,
    update,
)
from sqlalchemy.engine import Engine

from arbiter.results import RunResult, TrialResult

metadata = MetaData()

runs = Table(
    "runs", metadata,
    Column("id", String, primary_key=True),
    Column("created_at", String, nullable=False),
    Column("environment", String, nullable=False),
    Column("agent_type", String, nullable=False),
    Column("label", String, default=""),
    Column("config", JSON, nullable=False),
    Column("scenario_set", JSON, nullable=False),
    Column("summary", JSON, nullable=False),
    Column("spend", JSON, nullable=False),
    Column("git_sha", String),
    Column("aborted", Text),
    Column("source_path", String),
)

trials = Table(
    "trials", metadata,
    Column("pk", Integer, primary_key=True, autoincrement=True),
    Column("run_id", String, ForeignKey("runs.id", ondelete="CASCADE"), index=True, nullable=False),
    Column("scenario_id", String, index=True, nullable=False),
    Column("trial_index", Integer, nullable=False),
    Column("category", String, nullable=False),
    Column("success", Boolean, nullable=False),
    Column("status", String, nullable=False),
    Column("trace_id", String, index=True),
    Column("data", JSON, nullable=False),
)

approvals = Table(
    "approvals", metadata,
    Column("pk", Integer, primary_key=True, autoincrement=True),
    Column("run_id", String, index=True),
    Column("scenario_id", String),
    Column("trial_index", Integer),
    Column("approval_id", String),
    Column("action", String, nullable=False),
    Column("amount", Float),
    Column("reason", Text, default=""),
    Column("payload", JSON),
    Column("status", String, default="pending", index=True),
    Column("decided_by", String),
    Column("decided_at", DateTime),
    Column("note", Text),
)

labels = Table(
    "labels", metadata,
    Column("pk", Integer, primary_key=True, autoincrement=True),
    Column("item_id", String, index=True, nullable=False),
    Column("criterion", String, nullable=False),
    Column("verdict", String, nullable=False),
    Column("labeller", String, default="human"),
    Column("note", Text, default=""),
    Column("created_at", DateTime),
)


def database_url(explicit: str | None = None) -> str:
    return explicit or os.environ.get("ARBITER_DATABASE_URL") or "sqlite:///.arbiter/arbiter.db"


class Store:
    def __init__(self, url: str | None = None):
        url = database_url(url)
        if url.startswith("sqlite:///") and not url.startswith("sqlite:///:memory:"):
            Path(url.removeprefix("sqlite:///")).parent.mkdir(parents=True, exist_ok=True)
        self.engine: Engine = create_engine(url)
        metadata.create_all(self.engine)

    def save_run(self, run: RunResult, source_path: str | None = None) -> None:
        with self.engine.begin() as cx:
            cx.execute(delete(trials).where(trials.c.run_id == run.id))
            cx.execute(delete(approvals).where(approvals.c.run_id == run.id))
            cx.execute(delete(runs).where(runs.c.id == run.id))
            cx.execute(insert(runs).values(
                id=run.id, created_at=run.created_at, environment=run.environment, agent_type=run.agent_type,
                label=run.label, config=run.config, scenario_set=run.scenario_set, summary=run.summary,
                spend=run.spend, git_sha=run.git_sha, aborted=run.aborted, source_path=source_path,
            ))
            if run.trials:
                cx.execute(insert(trials), [{
                    "run_id": run.id, "scenario_id": t.scenario_id, "trial_index": t.trial_index,
                    "category": t.category, "success": t.success, "status": t.status, "trace_id": t.trace_id,
                    "data": t.model_dump(mode="json"),
                } for t in run.trials])
            pending = [(t, a) for t in run.trials for a in t.approvals]
            if pending:
                cx.execute(insert(approvals), [{
                    "run_id": run.id, "scenario_id": t.scenario_id, "trial_index": t.trial_index,
                    "approval_id": a.id, "action": a.action, "amount": a.amount, "reason": a.reason,
                    "payload": a.payload, "status": "pending",
                } for t, a in pending])

    def list_runs(self) -> list[dict[str, Any]]:
        with self.engine.connect() as cx:
            rows = cx.execute(select(runs).order_by(runs.c.created_at.desc())).mappings().all()
        return [dict(r) for r in rows]

    def list_runs_by_id(self, run_id: str) -> dict[str, Any]:
        with self.engine.connect() as cx:
            row = cx.execute(select(runs).where(runs.c.id == run_id)).mappings().first()
        return dict(row) if row else {}

    def get_run(self, run_id: str) -> RunResult | None:
        with self.engine.connect() as cx:
            row = cx.execute(select(runs).where(runs.c.id == run_id)).mappings().first()
            if row is None:
                return None
            trows = cx.execute(select(trials.c.data).where(trials.c.run_id == run_id)
                               .order_by(trials.c.scenario_id, trials.c.trial_index)).all()
        data = {k: row[k] for k in ("id", "created_at", "environment", "agent_type", "label", "config",
                                    "scenario_set", "summary", "spend", "git_sha", "aborted")}
        data["trials"] = [TrialResult.model_validate(r[0]) for r in trows]
        return RunResult.model_validate(data)

    def trial_by_trace(self, trace_id: str) -> dict[str, Any] | None:
        with self.engine.connect() as cx:
            row = cx.execute(select(trials.c.run_id, trials.c.data).where(trials.c.trace_id == trace_id)).first()
        return {"run_id": row[0], "trial": row[1]} if row else None

    def scenario_trials(self, run_id: str, scenario_id: str) -> list[dict[str, Any]]:
        with self.engine.connect() as cx:
            q = select(trials.c.data).where(trials.c.run_id == run_id, trials.c.scenario_id == scenario_id)
            rows = cx.execute(q.order_by(trials.c.trial_index)).all()
        return [r[0] for r in rows]

    def approvals(self, status: str | None = None) -> list[dict[str, Any]]:
        q = select(approvals).order_by(approvals.c.pk)
        if status:
            q = q.where(approvals.c.status == status)
        with self.engine.connect() as cx:
            return [dict(r) for r in cx.execute(q).mappings().all()]

    def decide_approval(self, pk: int, decision: str, by: str = "reviewer", note: str = "") -> bool:
        if decision not in ("approved", "rejected"):
            raise ValueError("decision must be approved or rejected")
        with self.engine.begin() as cx:
            res = cx.execute(update(approvals).where(approvals.c.pk == pk, approvals.c.status == "pending").values(
                status=decision, decided_by=by, decided_at=datetime.now(UTC), note=note))
        return res.rowcount == 1

    def save_label(self, item_id: str, criterion: str, verdict: str, labeller: str = "human", note: str = "") -> None:
        if verdict not in ("pass", "fail", "na"):
            raise ValueError("verdict must be pass, fail or na")
        with self.engine.begin() as cx:
            cx.execute(delete(labels).where(labels.c.item_id == item_id, labels.c.criterion == criterion,
                                            labels.c.labeller == labeller))
            cx.execute(insert(labels).values(item_id=item_id, criterion=criterion, verdict=verdict, labeller=labeller,
                                             note=note, created_at=datetime.now(UTC)))

    def get_labels(self, labeller: str = "human") -> list[dict[str, Any]]:
        with self.engine.connect() as cx:
            rows = cx.execute(select(labels).where(labels.c.labeller == labeller)).mappings().all()
        return [dict(r) for r in rows]


def write_run_json(run: RunResult, results_dir: str | Path) -> Path:
    path = Path(results_dir) / f"{run.id}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(run.model_dump(mode="json"), separators=(",", ":"), default=str))
    return path


def read_run_json(path: str | Path) -> RunResult:
    return RunResult.model_validate_json(Path(path).read_text())


def resolve_run(ref: str, results_dir: str | Path = "results/runs") -> RunResult:
    """Accept a path to a run JSON, a run id, or a unique id prefix."""
    p = Path(ref)
    if p.exists():
        return read_run_json(p)
    candidates = sorted(Path(results_dir).glob(f"{ref}*.json"))
    if len(candidates) == 1:
        return read_run_json(candidates[0])
    if not candidates:
        raise FileNotFoundError(f"no run matching {ref!r} in {results_dir}")
    raise ValueError(f"{ref!r} is ambiguous: {[c.stem for c in candidates[:5]]}")


def import_runs(store: Store, results_dir: str | Path = "results/runs") -> int:
    n = 0
    for path in sorted(Path(results_dir).rglob("*.json")):
        if "superseded" in path.parts:
            continue
        store.save_run(read_run_json(path), source_path=str(path))
        n += 1
    return n
