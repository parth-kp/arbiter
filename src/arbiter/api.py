"""Programmatic entry point: evaluate any agent class in a few lines."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

from arbiter.agents import register_agent
from arbiter.core.agent import Agent
from arbiter.results import RunResult


def evaluate(env: str, agent: type[Agent] | str = "reference", *, config: str | Path | None = None,
             scenarios: str = "scenarios", set: str = "golden", trials: int = 3, mode: str = "cache",
             save_db: bool = False, **overrides: Any) -> RunResult:
    """Run an evaluation and return the result (also written to results/runs as JSON).

    ``agent`` is a registered type ("reference", "openai", "http", "langgraph") or your own ``Agent`` subclass.
    Extra keyword arguments override config keys, using dots for nesting: ``**{"agent.model": "..."}``.
    """
    from arbiter.runner.service import execute_run

    agent_type = agent
    if isinstance(agent, type):
        agent_type = f"custom:{agent.__module__}.{agent.__qualname__}"
        register_agent(agent_type, lambda cfg, deps, cls=agent: cls(cfg))
    opts = {"agent.type": agent_type, "scenarios": scenarios, "set": set, "trials": trials, "mode": mode,
            **overrides}
    result, _ = asyncio.run(execute_run(env, str(config) if config else None, opts, save_db=save_db))
    return result
