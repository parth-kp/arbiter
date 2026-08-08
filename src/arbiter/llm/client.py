from __future__ import annotations

import asyncio
import time
from collections.abc import Callable

from opentelemetry import trace

from arbiter.llm.budget import RunBudget, SpendLedger
from arbiter.llm.cassette import Cassette, CassetteMode
from arbiter.llm.pricing import estimate_cost, estimate_prompt_tokens
from arbiter.llm.providers import ProviderChain
from arbiter.llm.types import CallRecord, ChatRequest, ChatResponse

tracer = trace.get_tracer("arbiter.llm")


class RateLimiter:
    """Token bucket on requests per minute, shared by every trial in a run."""

    def __init__(self, rpm: float | None):
        self.interval = 60.0 / rpm if rpm else 0.0
        self._next = 0.0
        self._lock = asyncio.Lock()

    async def wait(self) -> None:
        if not self.interval:
            return
        async with self._lock:
            now = time.monotonic()
            delay = self._next - now
            self._next = max(now, self._next) + self.interval
        if delay > 0:
            await asyncio.sleep(delay)


class LLMClient:
    def __init__(self, chain: ProviderChain | None = None, *, cassette: Cassette | None = None,
                 ledger: SpendLedger | None = None, run_id: str = "adhoc", run_budget: RunBudget | None = None,
                 max_concurrency: int = 8, rpm: float | None = None):
        self.chain = chain
        self.cassette = cassette if cassette is not None else Cassette(None, CassetteMode.LIVE)
        self.ledger = ledger
        self.run_id = run_id
        self.run_budget = run_budget
        self._sem = asyncio.Semaphore(max_concurrency)
        self._rate = RateLimiter(rpm)

    async def complete(self, req: ChatRequest, *, trial_key: str, purpose: str,
                       on_call: Callable[[CallRecord], None] | None = None) -> ChatResponse:
        key = req.cache_key(trial_key)
        with tracer.start_as_current_span(f"llm.{purpose}") as span:
            span.set_attribute("llm.model", req.model)
            span.set_attribute("llm.purpose", purpose)
            cached = self.cassette.lookup(key)
            if cached is not None:
                resp = cached
            else:
                resp = await self._live(req)
                self.cassette.store(key, resp)
            span.set_attribute("llm.provider", resp.provider)
            span.set_attribute("llm.from_cassette", resp.from_cassette)
            span.set_attribute("llm.prompt_tokens", resp.usage.prompt_tokens)
            span.set_attribute("llm.completion_tokens", resp.usage.completion_tokens)
            span.set_attribute("llm.cost_usd", 0.0 if resp.from_cassette else resp.usage.cost_usd)
        if on_call:
            on_call(CallRecord(
                purpose=purpose, model=req.model, provider=resp.provider,
                prompt_tokens=resp.usage.prompt_tokens, completion_tokens=resp.usage.completion_tokens,
                cost_usd=resp.usage.cost_usd, latency_ms=resp.latency_ms, from_cassette=resp.from_cassette,
                finish_reason=resp.finish_reason,
            ))
        return resp

    async def _live(self, req: ChatRequest) -> ChatResponse:
        if self.chain is None:
            raise RuntimeError("live call attempted but no provider chain is configured (offline mode)")
        body_chars = len(str(req.to_openai()))
        reserve = estimate_cost(req.model, estimate_prompt_tokens(body_chars), req.max_tokens)
        if self.ledger:
            self.ledger.reserve(reserve, self.run_budget)
        try:
            async with self._sem:
                await self._rate.wait()
                resp = await self.chain.complete(req)
        except BaseException:
            if self.ledger:
                self.ledger.release(reserve, self.run_budget)
            raise
        if self.ledger:
            self.ledger.settle(reserve, resp.usage.cost_usd, self.run_id, req.model, resp.provider, self.run_budget)
        return resp

    def close(self) -> None:
        self.cassette.flush()
