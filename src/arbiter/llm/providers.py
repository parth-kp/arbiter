from __future__ import annotations

import asyncio
import json
import os
import random
import time
from dataclasses import dataclass, field
from typing import Any

import httpx

from arbiter.llm.pricing import estimate_cost
from arbiter.llm.types import ChatRequest, ChatResponse, Message, ToolCall, Usage


@dataclass
class Provider:
    name: str
    base_url: str
    api_key_env: str | None = None
    api_key: str | None = None
    headers: dict[str, str] = field(default_factory=dict)

    def key(self) -> str | None:
        return self.api_key or (os.environ.get(self.api_key_env) if self.api_key_env else None)

    @property
    def available(self) -> bool:
        return self.api_key_env is None or bool(self.key())


VERCEL = Provider("vercel", "https://ai-gateway.vercel.sh/v1", "VERCEL_API_KEY")
OPENROUTER = Provider(
    "openrouter",
    "https://openrouter.ai/api/v1",
    "OPENROUTER_API_KEY",
    headers={"HTTP-Referer": "https://github.com/parthkp13/arbiter", "X-Title": "Arbiter"},
)
DEFAULT_CHAIN = [VERCEL, OPENROUTER]


class ProviderError(RuntimeError):
    def __init__(self, provider: str, status: int | None, message: str, fallback: bool):
        super().__init__(f"{provider}: {status} {message}")
        self.provider = provider
        self.status = status
        self.fallback = fallback


class AllProvidersFailed(RuntimeError):
    pass


RETRYABLE = {408, 409, 429, 500, 502, 503, 504, 529}
# Access errors mean "this gateway can't serve this model for us" (e.g. Vercel free tier returns 403
# RestrictedModelsError); the next provider may well succeed, so they trigger fallback, not retry.
FALLBACK_ONLY = {401, 402, 403, 404}


class ProviderChain:
    def __init__(self, providers: list[Provider] | None = None, *, timeout_s: float = 90.0,
                 max_retries: int = 3, backoff_s: float = 1.0, transport: httpx.AsyncBaseTransport | None = None):
        self.providers = providers if providers is not None else DEFAULT_CHAIN
        self.max_retries = max_retries
        self.backoff_s = backoff_s
        self._client = httpx.AsyncClient(timeout=timeout_s, transport=transport)
        # A gateway that refused a model for access reasons (e.g. free tier) will keep refusing it; skipping it
        # avoids paying a wasted round trip on every call of a run.
        self._refused: set[tuple[str, str]] = set()

    async def aclose(self) -> None:
        await self._client.aclose()

    async def complete(self, req: ChatRequest) -> ChatResponse:
        errors: list[str] = []
        for provider in self.providers:
            if not provider.available:
                errors.append(f"{provider.name}: no API key")
                continue
            if (provider.name, req.model) in self._refused:
                continue
            try:
                return await self._with_retries(provider, req)
            except ProviderError as exc:
                errors.append(str(exc))
                if exc.status in FALLBACK_ONLY:
                    self._refused.add((provider.name, req.model))
                if not exc.fallback:
                    raise
        raise AllProvidersFailed("; ".join(errors) or "no providers configured")

    async def _with_retries(self, provider: Provider, req: ChatRequest) -> ChatResponse:
        attempt = 0
        while True:
            try:
                return await self._call(provider, req)
            except ProviderError as exc:
                if exc.status in FALLBACK_ONLY or attempt >= self.max_retries or not _retryable(exc):
                    raise
            attempt += 1
            await asyncio.sleep(self.backoff_s * (2 ** (attempt - 1)) * (0.5 + random.random()))

    async def _call(self, provider: Provider, req: ChatRequest) -> ChatResponse:
        headers = {"Content-Type": "application/json", **provider.headers}
        if key := provider.key():
            headers["Authorization"] = f"Bearer {key}"
        started = time.perf_counter()
        try:
            resp = await self._client.post(f"{provider.base_url}/chat/completions", json=req.to_openai(),
                                           headers=headers)
        except (httpx.TimeoutException, httpx.TransportError) as exc:
            raise ProviderError(provider.name, None, f"transport error: {type(exc).__name__}", True) from exc
        latency_ms = (time.perf_counter() - started) * 1000
        if resp.status_code != 200:
            raise ProviderError(provider.name, resp.status_code, _error_text(resp), True)
        try:
            data = resp.json()
        except json.JSONDecodeError as exc:
            raise ProviderError(provider.name, 200, "malformed JSON body", True) from exc
        if "error" in data and not data.get("choices"):
            raise ProviderError(provider.name, _int(data["error"].get("code")), str(data["error"])[:200], True)
        return parse_openai_response(data, provider.name, req.model, latency_ms)


def _retryable(exc: ProviderError) -> bool:
    return exc.status is None or exc.status in RETRYABLE or exc.status == 200


def _int(v: Any) -> int | None:
    try:
        return int(v)
    except (TypeError, ValueError):
        return None


def _error_text(resp: httpx.Response) -> str:
    try:
        err = resp.json().get("error", {})
        if isinstance(err, dict):
            return str(err.get("message") or err)[:200]
        return str(err)[:200]
    except Exception:
        return resp.text[:200]


def parse_openai_response(data: dict[str, Any], provider: str, model: str, latency_ms: float) -> ChatResponse:
    choices = data.get("choices") or []
    if not choices:
        raise ProviderError(provider, 200, "response had no choices", True)
    choice = choices[0]
    msg = choice.get("message") or {}
    tool_calls = []
    for i, tc in enumerate(msg.get("tool_calls") or []):
        fn = tc.get("function") or {}
        raw = fn.get("arguments") or "{}"
        try:
            args = json.loads(raw) if isinstance(raw, str) else dict(raw)
            if not isinstance(args, dict):
                args = {"_value": args}
        except json.JSONDecodeError:
            args = {"_malformed_json": raw}
        tool_calls.append(ToolCall(id=tc.get("id") or f"call_{i}", name=fn.get("name", ""), arguments=args,
                                   raw_arguments=raw if isinstance(raw, str) else None))
    u = data.get("usage") or {}
    pt, ct = int(u.get("prompt_tokens") or 0), int(u.get("completion_tokens") or 0)
    cached = int((u.get("prompt_tokens_details") or {}).get("cached_tokens") or 0)
    if u.get("cost") is not None:
        usage = Usage(prompt_tokens=pt, completion_tokens=ct, cached_tokens=cached, cost_usd=float(u["cost"]),
                      cost_source="provider")
    else:
        usage = Usage(prompt_tokens=pt, completion_tokens=ct, cached_tokens=cached,
                      cost_usd=estimate_cost(model, pt, ct), cost_source="price_table")
    return ChatResponse(
        message=Message(role="assistant", content=msg.get("content"), tool_calls=tool_calls or None),
        usage=usage,
        model=data.get("model") or model,
        provider=provider,
        latency_ms=latency_ms,
        finish_reason=choice.get("finish_reason"),
    )
