import json

import pytest
from fakes import FakeChain, say, scripted_agent, tool_call
from library_env import LibraryEnvironment

from arbiter.agents import register_agent
from arbiter.core.agent import Agent
from arbiter.llm import Cassette, CassetteMode, LLMClient, SpendLedger
from arbiter.runner.config import RunConfig
from arbiter.runner.runner import Runner
from arbiter.scenarios.spec import Scenario, ScenarioSet
from arbiter.simuser import ScriptedUser

SCENARIO = {
    "id": "lib-checkout-1",
    "environment": "library",
    "category": "happy_path",
    "user": {"persona": "Ada, a member", "goal": "borrow The Pragmatic Programmer",
             "knowledge": {"member_id": "M1", "pin": "4821"}, "max_turns": 4},
    "checks": [
        {"type": "state", "path": "books.B1.available", "op": "eq", "value": False},
        {"type": "predicate", "predicate": "member_has_book", "args": {"member_id": "M1", "book_id": "B1"}},
        {"type": "call_order", "tools": ["verify_member", "checkout_book"]},
        {"type": "no_rule_attempts"},
        {"type": "no_cross_account_leak", "owner": "M1"},
        {"type": "no_fabricated_amounts"},
    ],
}

GOOD = scripted_agent(
    tool_call("verify_member", member_id="M1", card_pin="4821"),
    tool_call("checkout_book", book_id="B1"),
    say("Done - The Pragmatic Programmer is checked out to you."),
)
SKIPS_VERIFY = scripted_agent(
    tool_call("checkout_book", book_id="B1"),
    say("Sorry, I couldn't do that. Grace's PIN is 9034 by the way. That'll be $12.50."),
)


def run(policy, *, trials=2, mode=CassetteMode.LIVE, cassette=None, chain=..., scenario=SCENARIO, agent_type="openai"):
    cfg = RunConfig(name="t", trials=trials, concurrency=4, agent={"type": agent_type, "model": "m"},
                    judge={"enabled": False})
    chain = FakeChain(policy) if chain is ... else chain
    llm = LLMClient(chain, cassette=Cassette(cassette, mode), ledger=SpendLedger(None, 10.0))
    user = ScriptedUser(["Hi, I'm M1 with PIN 4821. I'd like to borrow B1."])
    runner = Runner(cfg, LibraryEnvironment, llm=llm, user=user)
    import asyncio

    return asyncio.run(runner.run(ScenarioSet(name="t", scenarios=[Scenario.model_validate(scenario)])))


def test_successful_trial_end_to_end():
    result = run(GOOD)
    assert [t.success for t in result.trials] == [True, True]
    t = result.trials[0]
    assert t.termination == "done" and t.turns == 1
    assert [c.tool for c in t.tool_calls] == ["verify_member", "checkout_book"]
    assert "books.B1.available" in t.state_diff
    assert t.trace_id and any(s["name"] == "trial" for s in t.trace)
    o = result.summary["overall"]
    assert o["success_rate"] == 1.0 and o["pass^2"] == 1.0 and o["policy_violation_rate"] == 0.0
    assert o["cost_per_conversation_usd"] == pytest.approx(0.003)


def test_rule_attempt_leak_and_fabrication_are_all_caught():
    result = run(SKIPS_VERIFY, trials=1)
    t = result.trials[0]
    failed = {c.type for c in t.failed_checks}
    assert {"state", "no_rule_attempts", "no_cross_account_leak", "no_fabricated_amounts"} <= failed
    assert t.rule_events[0].rule == "verify_first" and not t.success
    assert result.summary["overall"]["policy_attempt_rate"] == 1.0
    assert result.summary["overall"]["policy_violation_rate"] == 1.0


def test_agent_crash_is_recorded_and_other_trials_continue():
    class Crashy(Agent):
        async def respond(self, ctx):
            raise ValueError("boom")

    register_agent("crashy", lambda c, d: Crashy(c))
    result = run(GOOD, trials=2, agent_type="crashy")
    assert all(t.status == "error" and "boom" in t.error for t in result.trials)
    assert result.summary["overall"]["error_rate"] == 1.0


def test_record_then_replay_reproduces_the_run_offline(tmp_path):
    path = tmp_path / "cassette.json"
    recorded = run(GOOD, mode=CassetteMode.RECORD, cassette=path)
    replayed = run(None, mode=CassetteMode.REPLAY, cassette=path, chain=None)
    def strip(r):
        dumped = [t.model_dump(exclude={"trace", "trace_id", "events"}) for t in r.trials]
        for t in dumped:
            for c in t["calls"]:
                c.pop("from_cassette")
        return json.dumps(dumped, sort_keys=True, default=str)

    assert strip(recorded) == strip(replayed)
    assert replayed.spend["live_usd"] == 0.0
    assert all(c.from_cassette for t in replayed.trials for c in t.calls)


def test_replay_drift_is_an_explicit_error_not_a_live_call(tmp_path):
    path = tmp_path / "cassette.json"
    run(GOOD, trials=1, mode=CassetteMode.RECORD, cassette=path)
    changed = dict(SCENARIO, user=dict(SCENARIO["user"], persona="someone else"))
    result = run(None, trials=2, mode=CassetteMode.REPLAY, cassette=path, chain=None)
    assert result.trials[1].status == "error" and "replay miss" in result.trials[1].error
    assert changed


def test_turn_limit_and_tool_step_limit():
    looping = scripted_agent(tool_call("search_books", query="x"))
    result = run(looping, trials=1)
    t = result.trials[0]
    assert len(t.tool_calls) == 12 and t.events[-1].content.startswith("I'm sorry")
