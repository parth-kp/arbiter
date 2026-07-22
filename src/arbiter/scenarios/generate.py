"""Template-based scenario variation.

A template is a scenario with ``{{placeholders}}`` plus a list of parameter sets. Expansion is pure text
substitution, so it is deterministic, free, and reviewable in a diff. Generated scenarios record which template
they came from; pruning is done by deleting entries from the generated file.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import yaml

from arbiter.core.environment import Environment
from arbiter.scenarios.spec import Scenario
from arbiter.scenarios.validate import validate_scenario

_PH = re.compile(r"\{\{\s*([a-zA-Z_][a-zA-Z0-9_]*)\s*\}\}")


def render(template: str, params: dict[str, Any]) -> str:
    def sub(m: re.Match) -> str:
        key = m.group(1)
        if key not in params:
            raise KeyError(f"template placeholder {{{{{key}}}}} has no value")
        return str(params[key])

    return _PH.sub(sub, template)


def expand_template(path: Path) -> list[dict[str, Any]]:
    # The scenario block is rendered as text before parsing so unquoted placeholders can become numbers/booleans.
    text = path.read_text()
    marker = text.find("\nscenario:")
    if marker < 0:
        raise ValueError(f"{path}: template needs a top-level 'scenario:' block after its params")
    head = yaml.safe_load(text[:marker])
    body = text[marker + 1:]
    out = []
    for params in head["params"]:
        data = yaml.safe_load(render(body, params))["scenario"]
        data["generated_from"] = head["template_id"]
        out.append(data)
    return out


def generate(env_cls: type[Environment], root: Path, *, existing_ids: set[str]) -> tuple[list[dict], list[str]]:
    """Expand every template under ``root/templates``. Returns (accepted, rejection reasons)."""
    accepted: list[dict] = []
    rejected: list[str] = []
    seen_fingerprints: set[str] = set()
    for tpath in sorted((root / "templates").glob("*.yaml")):
        for data in expand_template(tpath):
            sid = data.get("id", "?")
            if sid in existing_ids:
                rejected.append(f"{sid}: id already exists")
                continue
            try:
                s = Scenario.model_validate(data)
            except Exception as exc:
                rejected.append(f"{sid}: invalid ({str(exc).splitlines()[0]})")
                continue
            problems = validate_scenario(s, env_cls)
            if problems:
                rejected.append(f"{sid}: {problems[0]}")
                continue
            fp = Scenario.model_validate({**data, "id": "x"}).fingerprint()
            if fp in seen_fingerprints:
                rejected.append(f"{sid}: duplicate of an earlier variation")
                continue
            seen_fingerprints.add(fp)
            existing_ids.add(sid)
            accepted.append(data)
    return accepted, rejected
