from __future__ import annotations

# USD per token, taken from the OpenRouter and Vercel AI Gateway model lists on 2026-11-09.
PRICES: dict[str, tuple[float, float]] = {
    "anthropic/claude-sonnet-5.5": (2.0e-6, 10.0e-6),
    "anthropic/claude-haiku-5.5": (0.10e-6, 0.50e-6),
    "openai/gpt-5-nano": (0.05e-6, 0.40e-6),
    "openai/gpt-5.6-luna": (0.20e-6, 1.20e-6),
}

# Unknown models are priced pessimistically so the budget guard errs on the side of stopping early.
UNKNOWN_PRICE: tuple[float, float] = (10.0e-6, 50.0e-6)


def price_for(model: str) -> tuple[float, float]:
    return PRICES.get(model, UNKNOWN_PRICE)


def estimate_cost(model: str, prompt_tokens: int, completion_tokens: int) -> float:
    pin, pout = price_for(model)
    return prompt_tokens * pin + completion_tokens * pout


def estimate_prompt_tokens(body_chars: int) -> int:
    return body_chars // 3 + 1
