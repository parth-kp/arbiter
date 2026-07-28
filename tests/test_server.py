import json

import pytest
from fastapi.testclient import TestClient
from test_store_triage_gate import make_run

from arbiter.core.environment import Approval
from arbiter.server import create_app
from arbiter.store import write_run_json


@pytest.fixture
def client(tmp_path):
    rd = tmp_path / "runs"
    a = make_run("run-a", [1, 1, 0])
    b = make_run("run-b", [1, 0, 1])
    b.trials[0].approvals = [Approval(id="APR-1", action="issue_refund", amount=250.0)]
    b.trials[0].trace_id = "t" * 32
    b.trials[0].trace = [{"name": "trial", "offset_ms": 0, "duration_ms": 5}]
    write_run_json(a, rd)
    write_run_json(b, rd)
    labels = tmp_path / "labels"
    labels.mkdir()
    (labels / "items.json").write_text(json.dumps([{"item_id": "i1", "goal": "g", "transcript": "USER: hi",
                                                   "events": []}]))
    app = create_app(db=f"sqlite:///{tmp_path}/d.db", results_dir=str(rd), labels_dir=str(labels), static_dir=None)
    return TestClient(app)


def test_runs_list_and_detail(client):
    runs = client.get("/api/runs").json()
    assert {r["id"] for r in runs} == {"run-a", "run-b"}
    d = client.get("/api/runs/run-a").json()
    assert len(d["scenarios"]) == 3 and d["summary"]["overall"]["n_trials"] == 9
    assert client.get("/api/runs/nope").status_code == 404


def test_compare_and_failures(client):
    c = client.get("/api/compare", params={"a": "run-a", "b": "run-b"}).json()
    assert c["comparison"]["newly_failing"] == ["s01"]
    assert client.get("/api/runs/run-a/failures").json()[0]["reason"] == "final_state:state"


def test_scenario_detail_and_trace(client):
    d = client.get("/api/runs/run-b/scenarios/s00").json()
    assert len(d["trials"]) == 3 and d["trials"][0]["trace_url"] == "/traces/" + "t" * 32
    assert client.get("/api/traces/" + "t" * 32).json()["spans"][0]["name"] == "trial"


def test_approval_queue_decisions(client):
    pending = client.get("/api/approvals", params={"status": "pending"}).json()
    assert pending[0]["amount"] == 250.0
    assert client.post(f"/api/approvals/{pending[0]['pk']}", json={"decision": "approved"}).status_code == 200
    assert client.post(f"/api/approvals/{pending[0]['pk']}", json={"decision": "rejected"}).status_code == 409


def test_labelling_roundtrip(client):
    assert client.post("/api/labels", json={"item_id": "i1", "criterion": "grounded_claims",
                                            "verdict": "pass"}).status_code == 200
    assert client.post("/api/labels", json={"item_id": "zz", "criterion": "x", "verdict": "pass"}).status_code == 404
    assert client.post("/api/labels", json={"item_id": "i1", "criterion": "x", "verdict": "?"}).status_code == 422
    data = client.get("/api/labels/items").json()
    assert data["labels"]["i1"]["grounded_claims"] == "pass" and "events" not in data["items"][0]
