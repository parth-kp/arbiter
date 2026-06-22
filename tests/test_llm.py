import asyncio
import json

import httpx
import pytest
import respx

from arbiter.llm import (
    BudgetExceeded,
    Cassette,
    CassetteMiss,
    CassetteMode,
    ChatRequest,
    LLMClient,
    Message,
    Provider,
    ProviderChain,
    RunBudget,
    SpendLedger,
)
from arbiter.llm.providers import AllProvidersFailed

A = Provider("a", "https://a.test/v1", api_key="ka")
B = Provider("b", "https://b.test/v1", api_key="kb")


def ok_body(content="hi", cost=0.001, tool_args=None):
    msg = {"role": "assistant", "content": content}
    if tool_args is not None:
        msg["tool_calls"] = [{"id": "c1", "type": "function", "function": {"name": "t", "arguments": tool_args}}]
    return {"choices": [{"message": msg, "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 10, "completion_tokens": 5, "cost": cost}}


def req(text="hello", model="anthropic/claude-haiku-5.5"):
    return ChatRequest(model=model, messages=[Message(role="user", content=text)], max_tokens=50)


@respx.mock
async def test_access_error_falls_back_to_next_provider():
    a = respx.post("https://a.test/v1/chat/completions").respond(403, json={"error": {"message": "free tier"}})
    b = respx.post("https://b.test/v1/chat/completions").respond(200, json=ok_body("from b"))
    chain = ProviderChain([A, B], backoff_s=0)
    resp = await chain.complete(req())
    assert resp.provider == "b" and resp.message.content == "from b"
    assert a.call_count == 1 and b.call_count == 1


@respx.mock
async def test_rate_limit_is_retried_on_same_provider():
    route = respx.post("https://a.test/v1/chat/completions").mock(
        side_effect=[httpx.Response(429), httpx.Response(200, json=ok_body())]
    )
    resp = await ProviderChain([A], backoff_s=0).complete(req())
    assert resp.provider == "a" and route.call_count == 2


@respx.mock
async def test_exhausted_server_errors_fall_back_then_fail_loudly():
    respx.post("https://a.test/v1/chat/completions").respond(500)
    respx.post("https://b.test/v1/chat/completions").respond(500)
    with pytest.raises(AllProvidersFailed):
        await ProviderChain([A, B], backoff_s=0, max_retries=1).complete(req())


@respx.mock
async def test_timeout_falls_back():
    respx.post("https://a.test/v1/chat/completions").mock(side_effect=httpx.ReadTimeout("slow"))
    respx.post("https://b.test/v1/chat/completions").respond(200, json=ok_body())
    resp = await ProviderChain([A, B], backoff_s=0, max_retries=0).complete(req())
    assert resp.provider == "b"


@respx.mock
async def test_malformed_tool_arguments_are_preserved_not_crashing():
    respx.post("https://a.test/v1/chat/completions").respond(200, json=ok_body(tool_args="{not json"))
    resp = await ProviderChain([A]).complete(req())
    assert resp.message.tool_calls[0].arguments == {"_malformed_json": "{not json"}


@respx.mock
async def test_cost_falls_back_to_price_table_when_provider_omits_it():
    body = ok_body()
    del body["usage"]["cost"]
    respx.post("https://a.test/v1/chat/completions").respond(200, json=body)
    resp = await ProviderChain([A]).complete(req())
    assert resp.usage.cost_source == "price_table"
    assert resp.usage.cost_usd == pytest.approx(10 * 0.10e-6 + 5 * 0.50e-6)


def test_missing_key_provider_is_skipped(monkeypatch):
    monkeypatch.delenv("NOPE_KEY", raising=False)
    assert not Provider("x", "https://x", "NOPE_KEY").available


@respx.mock
async def test_record_then_strict_replay_needs_no_network(tmp_path):
    respx.post("https://a.test/v1/chat/completions").respond(200, json=ok_body("recorded"))
    path = tmp_path / "c.json"
    rec = LLMClient(ProviderChain([A]), cassette=Cassette(path, CassetteMode.RECORD))
    await rec.complete(req(), trial_key="s1#0", purpose="agent")
    rec.close()

    replay = LLMClient(None, cassette=Cassette(path, CassetteMode.REPLAY))
    resp = await replay.complete(req(), trial_key="s1#0", purpose="agent")
    assert resp.message.content == "recorded" and resp.from_cassette
    with pytest.raises(CassetteMiss):
        await replay.complete(req("different"), trial_key="s1#0", purpose="agent")


@respx.mock
async def test_trial_index_is_part_of_the_cache_key(tmp_path):
    route = respx.post("https://a.test/v1/chat/completions").mock(
        side_effect=[httpx.Response(200, json=ok_body("t0")), httpx.Response(200, json=ok_body("t1"))]
    )
    client = LLMClient(ProviderChain([A]), cassette=Cassette(tmp_path / "c.json", CassetteMode.CACHE))
    r0 = await client.complete(req(), trial_key="s1#0", purpose="agent")
    r1 = await client.complete(req(), trial_key="s1#1", purpose="agent")
    r0b = await client.complete(req(), trial_key="s1#0", purpose="agent")
    assert (r0.message.content, r1.message.content, r0b.message.content) == ("t0", "t1", "t0")
    assert route.call_count == 2 and r0b.from_cassette


def test_cache_key_ignores_provider():
    assert req().cache_key("x") == req().cache_key("x")
    assert req().cache_key("x") != req().cache_key("y")


@respx.mock
async def test_concurrent_calls_cannot_overshoot_global_cap(tmp_path):
    async def slow(request):
        await asyncio.sleep(0.01)
        return httpx.Response(200, json=ok_body(cost=0.0001))

    respx.post("https://a.test/v1/chat/completions").mock(side_effect=slow)
    # Each call reserves ~ max_tokens*out_price + prompt estimate (~2.6e-5); a 1e-4 cap admits only a few.
    ledger = SpendLedger(tmp_path / "ledger.json", cap_usd=1e-4)
    client = LLMClient(ProviderChain([A]), ledger=ledger, run_id="r")
    results = await asyncio.gather(
        *[client.complete(req(), trial_key=f"k{i}", purpose="agent") for i in range(20)], return_exceptions=True
    )
    refused = [r for r in results if isinstance(r, BudgetExceeded)]
    assert refused, "cap should refuse some calls"
    assert ledger.reserved_usd == pytest.approx(0.0)
    succeeded = len(results) - len(refused)
    assert ledger.total_usd == pytest.approx(succeeded * 0.0001)
    saved = json.loads((tmp_path / "ledger.json").read_text())
    assert saved["runs"]["r"]["calls"] == succeeded


@respx.mock
async def test_run_budget_is_enforced_separately_from_global_cap():
    respx.post("https://a.test/v1/chat/completions").respond(200, json=ok_body(cost=0.00002))
    ledger = SpendLedger(None, cap_usd=100.0)
    client = LLMClient(ProviderChain([A]), ledger=ledger, run_budget=RunBudget(cap_usd=0.00005))
    await client.complete(req(), trial_key="a", purpose="agent")
    with pytest.raises(BudgetExceeded, match="run cap"):
        for i in range(10):
            await client.complete(req(), trial_key=f"b{i}", purpose="agent")


@respx.mock
async def test_failed_call_releases_its_reservation():
    respx.post("https://a.test/v1/chat/completions").respond(400, json={"error": {"message": "bad"}})
    ledger = SpendLedger(None, cap_usd=1.0)
    client = LLMClient(ProviderChain([A], max_retries=0), ledger=ledger)
    with pytest.raises(AllProvidersFailed):
        await client.complete(req(), trial_key="a", purpose="agent")
    assert ledger.reserved_usd == 0 and ledger.total_usd == 0


async def test_offline_client_refuses_live_calls():
    with pytest.raises(RuntimeError, match="offline"):
        await LLMClient(None).complete(req(), trial_key="a", purpose="agent")
