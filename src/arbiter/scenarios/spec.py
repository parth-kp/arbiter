from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, Field, field_validator

from arbiter.checks import Check, parse_check
from arbiter.core.environment import Fault

Cooperativeness = Literal["cooperative", "terse", "impatient", "confused", "adversarial"]


class UserSpec(BaseModel):
    persona: str
    goal: str
    knowledge: dict[str, Any] | str = Field(default_factory=dict)
    cooperativeness: Cooperativeness = "cooperative"
    max_turns: int = 8
    opening: str | None = None
    hidden: str | None = None

    def knowledge_text(self) -> str:
        if isinstance(self.knowledge, str):
            return self.knowledge
        return "\n".join(f"- {k}: {v}" for k, v in self.knowledge.items())


class Scenario(BaseModel):
    model_config = {"extra": "forbid"}

    id: str
    environment: str
    category: str
    tags: list[str] = Field(default_factory=list)
    golden: bool = False
    description: str = ""
    snapshot: str = "default"
    patch: dict[str, Any] | None = None
    faults: list[Fault] = Field(default_factory=list)
    user: UserSpec
    checks: list[Check]
    source: str | None = None
    generated_from: str | None = None

    @field_validator("checks", mode="before")
    @classmethod
    def _parse_checks(cls, v: list[Any]) -> list[Check]:
        return [parse_check(c) for c in v]

    def fingerprint(self) -> str:
        data = self.model_dump(mode="json", exclude={"source"})
        return hashlib.sha256(json.dumps(data, sort_keys=True).encode()).hexdigest()[:12]


class ScenarioSet(BaseModel):
    name: str
    scenarios: list[Scenario]

    @property
    def version(self) -> str:
        h = hashlib.sha256()
        for s in sorted(self.scenarios, key=lambda s: s.id):
            h.update(f"{s.id}:{s.fingerprint()}".encode())
        return h.hexdigest()[:12]

    def by_id(self) -> dict[str, Scenario]:
        return {s.id: s for s in self.scenarios}


def load_scenario_file(path: Path) -> list[Scenario]:
    raw = yaml.safe_load(path.read_text())
    items = raw if isinstance(raw, list) else [raw]
    out = []
    for item in items:
        try:
            s = Scenario.model_validate(item)
        except Exception as exc:
            sid = item.get("id", "?") if isinstance(item, dict) else "?"
            raise ValueError(f"{path}: scenario {sid}: {exc}") from exc
        s.source = str(path)
        out.append(s)
    return out


def load_scenarios(root: str | Path, *, environment: str | None = None) -> list[Scenario]:
    root = Path(root)
    files = [root] if root.is_file() else sorted(p for p in root.rglob("*.y*ml") if "sets" not in p.parts)
    scenarios: list[Scenario] = []
    seen: dict[str, str] = {}
    for f in files:
        for s in load_scenario_file(f):
            if s.id in seen:
                raise ValueError(f"duplicate scenario id {s.id} in {f} and {seen[s.id]}")
            seen[s.id] = str(f)
            if environment is None or s.environment == environment:
                scenarios.append(s)
    return scenarios


def select_set(scenarios: list[Scenario], spec: str, root: str | Path | None = None, *,
               categories: list[str] | None = None, limit: int | None = None) -> ScenarioSet:
    """Pick a named subset: ``all``, ``golden``, ``category:<name>``, ``tag:<name>``, or a set file of ids."""
    if spec == "all":
        chosen = list(scenarios)
    elif spec == "golden":
        chosen = [s for s in scenarios if s.golden]
    elif spec.startswith("category:"):
        chosen = [s for s in scenarios if s.category == spec.split(":", 1)[1]]
    elif spec.startswith("tag:"):
        chosen = [s for s in scenarios if spec.split(":", 1)[1] in s.tags]
    else:
        path = Path(spec)
        if not path.exists() and root is not None:
            path = Path(root) / "sets" / f"{spec}.txt"
        if not path.exists():
            raise FileNotFoundError(f"unknown scenario set {spec!r}")
        ids = [ln.split("#")[0].strip() for ln in path.read_text().splitlines()]
        ids = [i for i in ids if i]
        by_id = {s.id: s for s in scenarios}
        missing = [i for i in ids if i not in by_id]
        if missing:
            raise KeyError(f"set {spec} references unknown scenarios {missing[:5]}")
        chosen = [by_id[i] for i in ids]
    if categories:
        chosen = [s for s in chosen if s.category in categories]
    chosen = sorted(chosen, key=lambda s: s.id)
    if limit:
        chosen = chosen[:limit]
    return ScenarioSet(name=spec, scenarios=chosen)
