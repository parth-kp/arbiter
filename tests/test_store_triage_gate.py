import pytest

from arbiter.checks.base import CheckResult
from arbiter.core.environment import Approval, RuleEvent
from arbiter.gate import GatePolicy, gate
from arbiter.results import RunResult, TrialResult
from arbiter.stats import compare_runs, summarize
from arbiter.store import Store, read_run_json, resolve_run, write_run_json
from arbiter.triage import triage


def trial(sid, k, ok, *, cat="c", policy_fail=False, attempt=False, err=None):
    checks = [CheckResult(name="state", type="state", kind="final_state", passed=ok, detail="x")]
    if policy_fail:
        checks.append(CheckResult(name="no_leak", type="no_cross_account_leak", kind="policy", passed=False))
    return TrialResult(scenario_id=sid, category=cat, trial_index=k, success=ok and not policy_fail and not err,
                       checks=checks, status="error" if err else "completed", error=err,
                       rule_events=[RuleEvent(rule="r", tool="t", message="m")] if attempt else [])


def make_run(rid, rates, n_trials=3, **kw):
    ts = []
    for i, rate in enumerate(rates):
        for k in range(n_trials):
            ts.append(trial(f"s{i:02d}", k, k < round(rate * n_trials), cat="a" if i % 2 else "b", **kw))
    run = RunResult(id=rid, created_at="2026-11-09", environment="e", agent_type="reference",
                    config={"trials": n_trials}, scenario_set={"name": "x", "version": "v", "ids": []}, trials=ts)
    run.summary = summarize(run)
    return run


def test_store_roundtrip_and_approval_queue(tmp_path):
    store = Store(f"sqlite:///{tmp_path}/a.db")
    run = make_run("r1", [1, 0])
    run.trials[0].approvals = [Approval(id="APR-1", action="issue_refund", amount=250.0)]
    store.save_run(run)
    store.save_run(run)
    assert store.get_run("r1").summary == run.summary
    assert len(store.list_runs()) == 1
    pending = store.approvals("pending")
    assert len(pending) == 1 and pending[0]["amount"] == 250.0
    assert store.decide_approval(pending[0]["pk"], "approved", by="parth")
    assert not store.decide_approval(pending[0]["pk"], "rejected"), "decided approvals are immutable"
    with pytest.raises(ValueError):
        store.decide_approval(1, "maybe")


def test_labels_are_upserted(tmp_path):
    store = Store(f"sqlite:///{tmp_path}/a.db")
    store.save_label("i1", "grounded", "pass")
    store.save_label("i1", "grounded", "fail")
    assert [r["verdict"] for r in store.get_labels()] == ["fail"]


def test_json_export_and_resolution(tmp_path):
    run = make_run("20261109-abc", [1])
    path = write_run_json(run, tmp_path)
    assert read_run_json(path).id == run.id
    assert resolve_run("20261109", tmp_path).id == run.id


def test_triage_groups_by_most_important_failed_check():
    run = make_run("r", [0, 0, 1])
    run.trials.append(trial("s09", 0, True, policy_fail=True))
    run.trials.append(trial("s10", 0, False, err="replay miss: x"))
    pats = {p["reason"]: p for p in triage(run)}
    assert pats["final_state:state"]["count"] == 6
    assert pats["policy:no_leak"]["count"] == 1
    assert "error:replay miss" in pats
    assert pats["final_state:state"]["examples"][0]["scenario_id"] == "s00"


def test_compare_flags_new_failures_and_category_deltas():
    a = make_run("a", [1, 1, 1, 0])
    b = make_run("b", [1, 0, 1, 1])
    cmp = compare_runs(a, b)
    assert cmp["newly_failing"] == ["s01"] and cmp["newly_passing"] == ["s03"]
    assert set(cmp["by_category"]) == {"a", "b"}


def test_gate_fails_on_significant_regression():
    base = make_run("base", [1.0] * 20)
    worse = make_run("cand", [1.0] * 8 + [0.0] * 12)
    result = gate(base, worse)
    assert not result["passed"] and "success dropped" in result["reasons"][0]


def test_gate_passes_on_noise_and_improvement():
    base = make_run("base", [1.0] * 19 + [2 / 3])
    noisy = make_run("cand", [1.0] * 18 + [2 / 3, 1.0])
    assert gate(base, noisy)["passed"]
    assert gate(make_run("b", [0.5] * 10), make_run("c", [1.0] * 10))["passed"]


def test_gate_fails_on_violation_rise_and_errors():
    base = make_run("base", [1.0] * 12)
    leaky = make_run("cand", [1.0] * 12, policy_fail=True)
    assert any("violation" in r for r in gate(base, leaky)["reasons"])
    errored = make_run("cand2", [1.0] * 12, err="replay miss")
    assert any("errored" in r for r in gate(base, errored, GatePolicy())["reasons"])


def test_blocked_attempts_are_not_counted_as_violations():
    t = trial("s", 0, True, attempt=True)
    t.checks.append(CheckResult(name="no_rule_attempts", type="no_rule_attempts", kind="policy", passed=False))
    assert t.policy_attempts == 1 and not t.policy_violation


def test_outdated_sqlite_index_is_set_aside_and_rebuilt(tmp_path):
    import sqlite3

    db = tmp_path / "old.db"
    with sqlite3.connect(db) as cx:
        cx.execute("CREATE TABLE trials (pk INTEGER PRIMARY KEY, run_id TEXT)")
    store = Store(f"sqlite:///{db}")
    store.save_run(make_run("r1", [1]))
    assert (tmp_path / "old.db.bak").exists() and store.get_run("r1") is not None
