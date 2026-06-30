from __future__ import annotations

import json
import re
from collections.abc import Callable
from pathlib import Path

import yaml
from pydantic import BaseModel

from arbiter.checks.base import CheckResult
from arbiter.core.transcript import TranscriptEvent
from arbiter.llm.client import LLMClient
from arbiter.llm.types import CallRecord, ChatRequest, Message


class Criterion(BaseModel):
    id: str
    question: str
    passes_when: str
    fails_when: str
    not_applicable_when: str | None = None


class Rubric(BaseModel):
    name: str
    version: str
    description: str = ""
    criteria: list[Criterion]

    def select(self, ids: list[str] | None) -> list[Criterion]:
        if not ids:
            return self.criteria
        known = {c.id: c for c in self.criteria}
        missing = [i for i in ids if i not in known]
        if missing:
            raise KeyError(f"rubric {self.name} has no criteria {missing}")
        return [known[i] for i in ids]


def load_rubric(name: str, rubrics_dir: str | Path = "rubrics") -> Rubric:
    path = Path(rubrics_dir) / f"{name}.yaml"
    return Rubric.model_validate(yaml.safe_load(path.read_text()))


def render_transcript(events: list[TranscriptEvent], *, max_result_chars: int = 600) -> str:
    lines = []
    for e in events:
        if e.kind == "user":
            lines.append(f"USER: {e.content}")
        elif e.kind == "assistant":
            lines.append(f"ASSISTANT: {e.content}")
        elif e.kind == "tool_call":
            lines.append(f"  [tool call] {e.tool}({json.dumps(e.arguments, default=str)})")
        elif e.kind == "tool_result":
            body = json.dumps(e.result, default=str) if not isinstance(e.result, str) else e.result
            if len(body) > max_result_chars:
                body = body[:max_result_chars] + " …(truncated)"
            status = "ok" if e.ok else f"FAILED/{e.error_kind}"
            lines.append(f"  [tool result {status}] {body}")
        elif e.kind == "error":
            lines.append(f"  [error] {e.content}")
    return "\n".join(lines)


SYSTEM = """You are an expert evaluator of customer-facing AI assistants. You grade one conversation against a rubric.
Judge only what the transcript shows. Tool calls and results are visible to you but were not visible to the user.
Be strict and consistent: when a criterion's pass condition is not clearly met, it fails.

For each criterion answer "pass", "fail" or "na" (only when the criterion's not-applicable condition holds).
Reply with ONLY a JSON object mapping criterion id to {"verdict": "pass"|"fail"|"na", "reasoning": "<one or two
sentences citing the transcript>"}."""


def _criteria_block(criteria: list[Criterion]) -> str:
    out = []
    for c in criteria:
        out.append(f"## {c.id}\nQuestion: {c.question}\nPass when: {c.passes_when}\nFail when: {c.fails_when}")
        if c.not_applicable_when:
            out[-1] += f"\nNot applicable when: {c.not_applicable_when}"
    return "\n\n".join(out)


_JSON = re.compile(r"\{.*\}", re.S)


class Judge:
    def __init__(self, llm: LLMClient, model: str, rubrics_dir: str | Path = "rubrics"):
        self.llm = llm
        self.model = model
        self.rubrics_dir = rubrics_dir
        self._cache: dict[str, Rubric] = {}

    def rubric(self, name: str) -> Rubric:
        if name not in self._cache:
            self._cache[name] = load_rubric(name, self.rubrics_dir)
        return self._cache[name]

    async def grade(self, events: list[TranscriptEvent], rubric_name: str, criteria: list[str] | None, *,
                    goal: str, trial_key: str, required: bool,
                    on_call: Callable[[CallRecord], None] | None = None) -> list[CheckResult]:
        rubric = self.rubric(rubric_name)
        chosen = rubric.select(criteria)
        user = (f"# The user's goal\n{goal}\n\n# Rubric: {rubric.name} ({rubric.version})\n{_criteria_block(chosen)}"
                f"\n\n# Transcript\n{render_transcript(events)}")
        resp = await self.llm.complete(
            ChatRequest(model=self.model, messages=[Message(role="system", content=SYSTEM),
                                                    Message(role="user", content=user)],
                        temperature=0.0, max_tokens=900),
            trial_key=f"{trial_key}/judge:{rubric.name}:{rubric.version}", purpose="judge", on_call=on_call,
        )
        verdicts = parse_verdicts(resp.message.content or "")
        results = []
        for c in chosen:
            v = verdicts.get(c.id, {"verdict": "fail", "reasoning": "judge returned no verdict for this criterion"})
            verdict = v.get("verdict", "fail")
            results.append(CheckResult(
                name=f"judge:{rubric.name}:{c.id}", type="judge", kind="judge",
                passed=verdict in ("pass", "na"), required=required, detail=verdict,
                reasoning=v.get("reasoning", ""),
            ))
        return results


def parse_verdicts(text: str) -> dict[str, dict]:
    m = _JSON.search(text)
    if not m:
        return {}
    try:
        data = json.loads(m.group(0))
    except json.JSONDecodeError:
        return {}
    out = {}
    for k, v in data.items():
        if isinstance(v, str):
            v = {"verdict": v, "reasoning": ""}
        if isinstance(v, dict):
            verdict = str(v.get("verdict", "fail")).lower().strip()
            out[k] = {"verdict": verdict if verdict in ("pass", "fail", "na") else "fail",
                      "reasoning": v.get("reasoning", "")}
    return out
