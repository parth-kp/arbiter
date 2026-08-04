"""Executes docs/EXTENDING.md: every `# file:` block is written to a temp project and exercised."""

import asyncio
import re
import sys
from pathlib import Path

import pytest
from fakes import FakeChain, say, scripted_agent, tool_call

from arbiter.agents import register_agent
from arbiter.checks import check_types
from arbiter.llm import LLMClient
from arbiter.runner.config import RunConfig
from arbiter.runner.runner import Runner
from arbiter.scenarios import load_scenarios, select_set
from arbiter.scenarios.generate import generate
from arbiter.scenarios.validate import validate_scenario
from arbiter.simuser import ScriptedUser

GUIDE = Path(__file__).resolve().parents[1] / "docs" / "EXTENDING.md"
BLOCK = re.compile(r"```(?:python|yaml|markdown)\n# file: (\S+)\n(.*?)```", re.S)


@pytest.fixture(scope="module")
def project(tmp_path_factory):
    root = tmp_path_factory.mktemp("guide")
    blocks = BLOCK.findall(GUIDE.read_text())
    assert len(blocks) >= 7, "the guide lost some of its runnable examples"
    for rel, body in blocks:
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        if rel.endswith(".md"):
            body = body.lstrip("\n")
        path.write_text(body)
    sys.path.insert(0, str(root))
    yield root
    sys.path.remove(str(root))
    for mod in [m for m in sys.modules if m.startswith("rooms_env")]:
        del sys.modules[mod]


def test_guide_environment_rules_tests_pass(project):
    ns: dict = {}
    exec((project / "tests" / "test_rooms_rules.py").read_text(), ns)
    ns["test_double_booking_is_blocked_and_recorded"]()
    ns["test_bad_arguments_get_a_readable_error"]()


def test_guide_scenarios_validate_and_templates_generate(project):
    from rooms_env import RoomsEnvironment

    scen = load_scenarios(project / "scenarios" / "rooms")
    assert {s.id for s in scen} == {"rooms-book-standup", "rooms-too-long"}
    assert [p for s in scen for p in validate_scenario(s, RoomsEnvironment)] == []
    accepted, rejected = generate(RoomsEnvironment, project / "scenarios" / "rooms", existing_ids={s.id for s in scen})
    assert [a["id"] for a in accepted] == ["rooms-gen-small", "rooms-gen-large"] and rejected == []


def test_guide_custom_check_registers(project):
    import rooms_env.checks  # noqa: F401

    assert "max_failed_tool_calls" in check_types()


def _run(env_cls, agent_type, scenario_set, chain=None):
    cfg = RunConfig(name="guide", trials=2, agent={"type": agent_type, "model": "m"}, judge={"enabled": False})
    runner = Runner(cfg, env_cls, llm=LLMClient(chain), user=ScriptedUser(["Book a room for 10 people, 14-15."]))
    return asyncio.run(runner.run(scenario_set))


def test_guide_custom_agent_passes_the_golden_scenario(project):
    from rooms_env import RoomsEnvironment
    from rooms_env.agent import GreedyBooker

    register_agent("rooms_env.agent:GreedyBooker", lambda c, d: GreedyBooker(c))
    golden = select_set(load_scenarios(project / "scenarios" / "rooms"), "golden")
    result = _run(RoomsEnvironment, "rooms_env.agent:GreedyBooker", golden)
    assert [t.success for t in result.trials] == [True, True], result.trials[0].checks


def test_guide_environment_works_with_a_model_driven_agent(project):
    from rooms_env import RoomsEnvironment

    policy = scripted_agent(tool_call("find_rooms", min_seats=10),
                            tool_call("book_room", room_id="R2", start_hour=14, end_hour=15, owner="sam"),
                            say("Booked Glacier 14:00-15:00."))
    golden = select_set(load_scenarios(project / "scenarios" / "rooms"), "golden")
    result = _run(RoomsEnvironment, "openai", golden, chain=FakeChain(policy))
    assert all(t.success for t in result.trials)
