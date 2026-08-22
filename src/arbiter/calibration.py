"""Judge calibration: sample transcripts for human labelling, run the judge on them, and measure agreement."""

from __future__ import annotations

import json
import random
from collections import defaultdict
from pathlib import Path
from typing import Any

from arbiter.judge import Judge, Rubric, render_transcript
from arbiter.results import RunResult
from arbiter.stats import bootstrap_ci

LABELS_DIR = Path("labels")


def sample_items(runs: list[RunResult], n: int, *, seed: int = 7) -> list[dict[str, Any]]:
    """Stratified sample of completed trials: up to half failures, the rest successes, one trial per scenario
    before any scenario repeats, so the labelled set covers as many situations as possible."""
    pool = [(r, t) for r in runs for t in r.trials if t.status == "completed" and t.turns > 0]
    rng = random.Random(seed)
    rng.shuffle(pool)
    fails = [p for p in pool if not p[1].success]
    wins = [p for p in pool if p[1].success]
    chosen: list = []
    used: set = set()

    def take(bucket, limit, distinct):
        for r, t in bucket:
            if len(chosen) >= limit:
                return
            key = (r.id, t.scenario_id, t.trial_index)
            if key in used or (distinct and any(c[1].scenario_id == t.scenario_id for c in chosen)):
                continue
            used.add(key)
            chosen.append((r, t))

    take(fails, n // 2, distinct=True)
    take(fails, n // 2, distinct=False)
    take(wins, n, distinct=True)
    take(wins, n, distinct=False)
    items = []
    for r, t in chosen:
        items.append({
            "item_id": f"{r.id}:{t.scenario_id}:{t.trial_index}",
            "run_id": r.id, "environment": r.environment, "scenario_id": t.scenario_id,
            "trial_index": t.trial_index, "category": t.category,
            "goal": next((e.content for e in t.events if e.kind == "user"), "") or "",
            "transcript": render_transcript(t.events),
            "events": [e.model_dump(mode="json") for e in t.events],
        })
    return items


def cohen_kappa(a: list[str], b: list[str]) -> float | None:
    if not a:
        return None
    labels = sorted(set(a) | set(b))
    n = len(a)
    po = sum(x == y for x, y in zip(a, b, strict=True)) / n
    pe = sum((a.count(lab) / n) * (b.count(lab) / n) for lab in labels)
    if pe == 1.0:
        return 1.0 if po == 1.0 else 0.0
    return (po - pe) / (1 - pe)


def agreement_report(human: dict[str, dict[str, str]], judge: dict[str, dict[str, str]],
                     criteria: list[str]) -> dict[str, Any]:
    """Per-criterion agreement and Cohen's kappa with bootstrap CIs over items. 'na' is treated as its own label."""
    out: dict[str, Any] = {}
    for c in criteria:
        pairs = [(human[i][c], judge[i][c]) for i in human if c in human[i] and i in judge and c in judge[i]]
        if not pairs:
            out[c] = {"n": 0}
            continue
        hs, js = [p[0] for p in pairs], [p[1] for p in pairs]
        idx = list(range(len(pairs)))
        kappa_ci = bootstrap_ci(
            idx, lambda ii, hs=hs, js=js: cohen_kappa([hs[i] for i in ii], [js[i] for i in ii]) or 0.0)
        confusion: dict[str, int] = defaultdict(int)
        for h, j in pairs:
            confusion[f"human={h}/judge={j}"] += 1
        out[c] = {
            "n": len(pairs),
            "agreement": sum(h == j for h, j in pairs) / len(pairs),
            "kappa": cohen_kappa(hs, js),
            "kappa_ci95": kappa_ci,
            "human_pass_rate": hs.count("pass") / len(hs),
            "judge_pass_rate": js.count("pass") / len(js),
            "confusion": dict(confusion),
        }
    return out


async def run_judge_on_items(judge: Judge, rubric: Rubric, items: list[dict[str, Any]]) -> dict[str, dict[str, str]]:
    from arbiter.core.transcript import TranscriptEvent

    out: dict[str, dict[str, str]] = {}
    for item in items:
        events = [TranscriptEvent.model_validate(e) for e in item["events"]]
        results = await judge.grade(events, rubric.name, None, goal=item["goal"], trial_key=f"calib/{item['item_id']}",
                                    required=False)
        out[item["item_id"]] = {r.name.rsplit(":", 1)[-1]: r.detail for r in results}
        out[item["item_id"]]["_reasoning"] = json.dumps({r.name.rsplit(":", 1)[-1]: r.reasoning for r in results})
    return out


def load_items(path: Path = LABELS_DIR / "items.json") -> list[dict[str, Any]]:
    return json.loads(path.read_text()) if path.exists() else []


def load_human_labels(path: Path = LABELS_DIR / "human_labels.json") -> dict[str, dict[str, str]]:
    return json.loads(path.read_text()) if path.exists() else {}


def save_human_label(item_id: str, criterion: str, verdict: str, path: Path = LABELS_DIR / "human_labels.json") -> None:
    if verdict not in ("pass", "fail", "na"):
        raise ValueError("verdict must be pass, fail or na")
    labels = load_human_labels(path)
    labels.setdefault(item_id, {})[criterion] = verdict
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(labels, indent=1, sort_keys=True))
