from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, Field

from arbiter.core.agent import AgentConfig
from arbiter.llm.cassette import CassetteMode


class UserModelConfig(BaseModel):
    model: str = "anthropic/claude-haiku-5.5"
    temperature: float = 0.7


class JudgeConfig(BaseModel):
    enabled: bool = True
    model: str = "anthropic/claude-sonnet-5.5"
    rubrics_dir: str = "rubrics"


class RunConfig(BaseModel):
    """A complete, reproducible description of an eval run. Saved verbatim with the results."""

    name: str = "run"
    label: str = ""
    environment: str | None = None
    agent: AgentConfig = Field(default_factory=AgentConfig)
    user: UserModelConfig = Field(default_factory=UserModelConfig)
    judge: JudgeConfig = Field(default_factory=JudgeConfig)
    trials: int = 3
    concurrency: int = 4
    rpm: float | None = 120
    budget_usd: float = 0.50
    global_cap_usd: float = 5.00
    mode: CassetteMode = CassetteMode.CACHE
    cassette: str | None = None
    ledger: str = "results/spend_ledger.json"
    scenarios: str = "scenarios"
    set: str = "golden"
    categories: list[str] | None = None
    limit: int | None = None
    results_dir: str = "results/runs"
    db: str | None = None

    @classmethod
    def load(cls, path: str | Path | None, overrides: dict[str, Any] | None = None) -> RunConfig:
        data: dict[str, Any] = {}
        if path:
            data = yaml.safe_load(Path(path).read_text()) or {}
        for key, value in (overrides or {}).items():
            if value is None:
                continue
            target = data
            parts = key.split(".")
            for p in parts[:-1]:
                target = target.setdefault(p, {})
            target[parts[-1]] = value
        return cls.model_validate(data)

    def cassette_path(self, environment: str) -> str:
        return self.cassette or f"cassettes/{environment}/{self.name}.json"
