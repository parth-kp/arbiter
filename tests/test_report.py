import yaml
from test_store_triage_gate import make_run

from arbiter.report import render
from arbiter.store import write_run_json


def test_report_renders_tables_and_comparisons_from_run_json(tmp_path):
    rd = tmp_path / "runs"
    write_run_json(make_run("base", [1, 1, 0, 1]), rd)
    write_run_json(make_run("cand", [1, 0, 0, 1]), rd)
    spec = tmp_path / "e.yaml"
    spec.write_text(yaml.safe_dump({"experiments": [{
        "title": "Exp", "environments": {"store": [{"name": "v1", "run": "base"}, {"name": "v2", "run": "cand"}]},
        "compare": [["v1", "v2"]]}]}))
    md = render(spec, results_dir=str(rd))
    assert "| v1 | [base](../results/runs/base.json)" in md
    assert "Newly failing (1): `s01`" in md
    assert "pass^3" in md or "(k=3)" in md


def test_complete_scenarios_only_drops_scenarios_cut_short_in_any_arm(tmp_path):
    from arbiter.report import complete_scenarios

    a = make_run("a", [1, 1, 1])
    b = make_run("b", [1, 1, 1])
    b.trials[0].status = "error"
    assert complete_scenarios([a, b]) == {"s01", "s02"}
    rd = tmp_path / "runs"
    write_run_json(a, rd)
    write_run_json(b, rd)
    spec = tmp_path / "e.yaml"
    spec.write_text(yaml.safe_dump({"experiments": [{"title": "E", "complete_scenarios_only": True,
                                                    "environments": {"x": [{"name": "A", "run": "a"},
                                                                           {"name": "B", "run": "b"}]}}]}))
    md = render(spec, results_dir=str(rd))
    assert "only the 2 of 3 scenarios" in md and "| A | [a]" in md and "| 6 |" in md
