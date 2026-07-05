from __future__ import annotations

from pathlib import Path
from typing import Any

from arbiter.core.registry import get_environment
from arbiter.judge import Judge
from arbiter.llm import Cassette, CassetteMode, LLMClient, ProviderChain, RunBudget, SpendLedger
from arbiter.results import RunResult
from arbiter.runner.config import RunConfig
from arbiter.runner.runner import Runner, new_run_id
from arbiter.scenarios import load_scenarios, select_set
from arbiter.simuser import LLMUser
from arbiter.store import Store, write_run_json


async def execute_run(env: str, config_path: str | None, overrides: dict[str, Any] | None = None, *,
                      save_db: bool = True) -> tuple[RunResult, Path]:
    cfg = RunConfig.load(config_path, overrides)
    env_cls = get_environment(env)
    root = Path(cfg.scenarios) / env_cls.name
    scenarios = select_set(load_scenarios(root, environment=env_cls.name), cfg.set, root,
                           categories=cfg.categories, limit=cfg.limit)
    if not scenarios.scenarios:
        raise ValueError(f"scenario set {cfg.set!r} is empty for {env_cls.name}")
    run_id = new_run_id(cfg.name)
    chain = None if cfg.mode == CassetteMode.REPLAY else ProviderChain()
    llm = LLMClient(chain, cassette=Cassette(cfg.cassette_path(env_cls.name), cfg.mode),
                    ledger=SpendLedger(cfg.ledger, cfg.global_cap_usd), run_id=run_id,
                    run_budget=RunBudget(cfg.budget_usd), max_concurrency=cfg.concurrency * 2, rpm=cfg.rpm)
    judge = Judge(llm, cfg.judge.model, cfg.judge.rubrics_dir) if cfg.judge.enabled else None
    runner = Runner(cfg, env_cls, llm=llm, user=LLMUser(llm, cfg.user.model, temperature=cfg.user.temperature),
                    judge=judge, run_id=run_id)
    try:
        result = await runner.run(scenarios)
    finally:
        if chain is not None:
            await chain.aclose()
    path = write_run_json(result, cfg.results_dir)
    if save_db:
        Store(cfg.db).save_run(result, source_path=str(path))
    return result, path
