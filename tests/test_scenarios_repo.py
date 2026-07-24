"""Guards on the committed scenario library itself."""

from pathlib import Path

import pytest

from arbiter.core.registry import get_environment
from arbiter.scenarios import load_scenarios
from arbiter.scenarios.validate import validate_scenario

ROOT = Path(__file__).resolve().parents[1] / "scenarios"
ENVS = ["store", "productivity"]


@pytest.mark.parametrize("env", ENVS)
def test_every_scenario_validates(env):
    cls = get_environment(env)
    problems = [p for s in load_scenarios(ROOT / env) for p in validate_scenario(s, cls)]
    assert problems == []


def test_at_least_150_scenarios_across_both_environments():
    assert sum(len(load_scenarios(ROOT / e)) for e in ENVS) >= 150


@pytest.mark.parametrize("env", ENVS)
def test_golden_set_is_frozen_at_20_per_environment(env):
    scenarios = load_scenarios(ROOT / env)
    flagged = sorted(s.id for s in scenarios if s.golden)
    listed = sorted(ln.strip() for ln in (ROOT / env / "sets" / "golden.txt").read_text().splitlines()
                    if ln.strip() and not ln.startswith("#"))
    assert flagged == listed, "golden flags drifted from the frozen list; update both deliberately"
    assert len(listed) == 20


@pytest.mark.parametrize("env", ENVS)
def test_golden_set_covers_every_category(env):
    cats = {s.category for s in load_scenarios(ROOT / env) if s.golden}
    assert {"happy_path", "ambiguous", "multi_step", "policy_edge", "adversarial", "tool_failure",
            "out_of_scope"} <= cats
