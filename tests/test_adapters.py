import asyncio
import json

import httpx
import pytest
from fakes import FakeChain, say, scripted_agent, tool_call
from library_env import LibraryEnvironment
from test_runner_e2e import SCENARIO

from arbiter.agents.http import HTTPAgent, HTTPAgentError, parse_reply
from arbiter.agents.openai_shim import request_from_openai
from arbiter.core.agent import AgentConfig, AgentDeps
from arbiter.llm import Cassette, CassetteMode, LLMClient, SpendLedger
from arbiter.runner.config import RunConfig
from arbiter.runner.runner import Runner
from arbiter.scenarios.spec import Scenario, ScenarioSet
from arbiter.simuser import ScriptedUser


def run_with(agent_cfg, llm, user_lines=("I'm M1, PIN 4821. Please check out B1.",)):
    cfg = RunConfig(name="t", trials=1, agent=agent_cfg, judge={"enabled": False})
    runner = Runner(cfg, LibraryEnvironment, llm=llm, user=ScriptedUser(list(user_lines)))
    return asyncio.run(runner.run(ScenarioSet(name="t", scenarios=[Scenario.model_validate(SCENARIO)])))


class FakeHTTPAgentServer(httpx.AsyncBaseTransport):
    """A stand-in for someone else's agent service implementing arbiter-agent/1."""

    def __init__(self):
        self.bodies = []

    async def handle_async_request(self, request):
        body = json.loads(request.content)
        self.bodies.append(body)
        assert body["protocol"] == "arbiter-agent/1"
        n_tool = sum(1 for m in body["messages"] if m["role"] == "tool")
        if n_tool == 0:
            out = {"type": "tool_calls", "tool_calls": [
                {"id": "a", "name": "verify_member", "arguments": {"member_id": "M1", "card_pin": "4821"}}]}
        elif n_tool == 1:
            out = {"type": "tool_calls", "tool_calls": [{"id": "b", "name": "checkout_book",
                                                         "arguments": json.dumps({"book_id": "B1"})}]}
        else:
            out = {"type": "message", "content": "All done.", "usage": {"cost_usd": 0.002}}
        return httpx.Response(200, json=out)


def test_http_agent_is_driven_through_protocol_and_replays(tmp_path, monkeypatch):
    server = FakeHTTPAgentServer()
    import arbiter.agents.http as http_mod

    orig = http_mod.HTTPAgent.__init__
    monkeypatch.setattr(http_mod.HTTPAgent, "__init__",
                        lambda self, c, d, transport=None: orig(self, c, d, transport=server))
    path = tmp_path / "c.json"
    llm = LLMClient(None, cassette=Cassette(path, CassetteMode.RECORD))
    res = run_with({"type": "http", "endpoint": "http://agent.test/turn"}, llm)
    assert res.trials[0].success, res.trials[0].checks
    assert server.bodies[0]["tools"] and server.bodies[-1]["messages"][-1]["role"] == "tool"
    assert res.trials[0].cost_usd == pytest.approx(0.002)

    server.bodies.clear()
    replay = run_with({"type": "http", "endpoint": "http://agent.test/turn"},
                      LLMClient(None, cassette=Cassette(path, CassetteMode.REPLAY)))
    assert replay.trials[0].success and server.bodies == []


def test_http_reply_validation():
    with pytest.raises(HTTPAgentError):
        parse_reply({"type": "something"})
    with pytest.raises(HTTPAgentError):
        parse_reply({"type": "tool_calls", "tool_calls": []})
    with pytest.raises(ValueError):
        HTTPAgent(AgentConfig(type="http"), AgentDeps())


def test_shim_parses_openai_sdk_requests():
    body = {"model": "m", "temperature": None, "messages": [
        {"role": "developer", "content": [{"type": "text", "text": "sys"}]},
        {"role": "assistant", "content": None, "tool_calls": [
            {"id": "1", "type": "function", "function": {"name": "f", "arguments": "{\"a\": 1}"}}]},
        {"role": "tool", "tool_call_id": "1", "content": "ok"}],
        "tools": [{"type": "function", "function": {"name": "f", "parameters": {"type": "object"}}}]}
    req = request_from_openai(body)
    assert req.messages[0].role == "system" and req.messages[0].content == "sys"
    assert req.messages[1].tool_calls[0].arguments == {"a": 1}
    assert req.temperature == 0.0 and req.tools[0].name == "f"


def test_langgraph_agent_runs_through_arbiter_and_replays_offline(tmp_path):
    pytest.importorskip("langgraph")
    policy = scripted_agent(
        tool_call("verify_member", member_id="M1", card_pin="4821"),
        tool_call("checkout_book", book_id="B1"),
        say("Checked out."),
    )
    path = tmp_path / "lg.json"
    cfg = {"type": "langgraph", "model": "m", "graph": "langgraph_agent.graph:build_graph"}
    chain = FakeChain(policy)
    rec = run_with(cfg, LLMClient(chain, cassette=Cassette(path, CassetteMode.RECORD), ledger=SpendLedger(None, 1)))
    t = rec.trials[0]
    assert t.success, (t.error, [c for c in t.checks if not c.passed])
    assert [c.tool for c in t.tool_calls] == ["verify_member", "checkout_book"]
    assert chain.requests[0].messages[0].content.startswith("You are a careful support agent")
    assert len(t.calls) == 3

    rep = run_with(cfg, LLMClient(None, cassette=Cassette(path, CassetteMode.REPLAY)))
    assert rep.trials[0].success and all(c.from_cassette for c in rep.trials[0].calls)
