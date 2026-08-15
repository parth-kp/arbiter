from __future__ import annotations

import asyncio
import subprocess
import time
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import yaml
from opentelemetry import trace

import arbiter
from arbiter.agents import create_agent
from arbiter.checks.base import CheckContext, CheckResult
from arbiter.checks.builtin import JudgeCheck
from arbiter.core.agent import AgentDeps, TurnContext
from arbiter.core.environment import Environment
from arbiter.core.transcript import ToolCallRecord, TranscriptEvent
from arbiter.judge import Judge
from arbiter.llm.budget import BudgetExceeded
from arbiter.llm.cassette import CassetteMiss
from arbiter.llm.client import LLMClient
from arbiter.llm.types import CallRecord, Message
from arbiter.results import RunResult, TrialResult
from arbiter.runner.config import RunConfig
from arbiter.scenarios.spec import Scenario, ScenarioSet
from arbiter.simuser import UserSimulator
from arbiter.stats import summarize
from arbiter.tracing import collector, setup_tracing

tracer = trace.get_tracer("arbiter.runner")


def state_diff(before: Any, after: Any, path: str = "") -> dict[str, Any]:
    if isinstance(before, dict) and isinstance(after, dict):
        out: dict[str, Any] = {}
        for k in sorted(set(before) | set(after), key=str):
            p = f"{path}.{k}" if path else str(k)
            if k not in after:
                out[p] = {"before": before[k], "after": None, "removed": True}
            elif k not in before:
                out[p] = {"before": None, "after": after[k], "added": True}
            else:
                out.update(state_diff(before[k], after[k], p))
        return out
    return {} if before == after else {path: {"before": before, "after": after}}


def load_tool_descriptions(env_cls: type[Environment], name: str) -> dict[str, str] | None:
    if name in ("default", "", None) or env_cls.fixtures_dir is None:
        return None
    path = Path(env_cls.fixtures_dir) / "tool_descriptions" / f"{name}.yaml"
    if not path.exists():
        raise FileNotFoundError(f"tool description set {name!r} not found at {path}")
    return yaml.safe_load(path.read_text())


class Runner:
    def __init__(self, config: RunConfig, env_cls: type[Environment], *, llm: LLMClient, user: UserSimulator,
                 judge: Judge | None = None, prompts_dir: Path | None = None, run_id: str | None = None):
        self.config = config
        self.env_cls = env_cls
        self.llm = llm
        self.user = user
        self.judge = judge
        self.prompts_dir = prompts_dir
        self.run_id = run_id or new_run_id(config.name)
        self.tool_descriptions = load_tool_descriptions(env_cls, config.agent.tool_descriptions)
        self._abort: str | None = None
        setup_tracing()

    async def run(self, scenario_set: ScenarioSet) -> RunResult:
        sem = asyncio.Semaphore(self.config.concurrency)
        jobs = [(s, k) for s in scenario_set.scenarios for k in range(self.config.trials)]

        async def one(s: Scenario, k: int) -> TrialResult:
            async with sem:
                if self._abort:
                    return _aborted_trial(s, k, self._abort)
                return await self.run_trial(s, k)

        trials = await asyncio.gather(*(one(s, k) for s, k in jobs))
        self.llm.close()
        result = RunResult(
            id=self.run_id,
            created_at=datetime.now(UTC).isoformat(timespec="seconds"),
            environment=self.env_cls.name,
            agent_type=self.config.agent.type,
            label=self.config.label,
            config=self.config.model_dump(mode="json"),
            scenario_set={"name": scenario_set.name, "version": scenario_set.version,
                          "ids": [s.id for s in scenario_set.scenarios]},
            trials=sorted(trials, key=lambda t: (t.scenario_id, t.trial_index)),
            git_sha=_git_sha(),
            arbiter_version=arbiter.__version__,
            aborted=self._abort,
        )
        result.spend = {
            "live_usd": round(sum(c.cost_usd for t in trials for c in t.calls if not c.from_cassette), 6),
            "agent_cost_usd": round(sum(t.cost_usd for t in trials), 6),
            "eval_overhead_usd": round(sum(t.eval_cost_usd for t in trials), 6),
        }
        result.summary = summarize(result, k=self.config.trials)
        return result

    async def run_trial(self, scenario: Scenario, k: int) -> TrialResult:
        trial_key = f"{scenario.id}#{k}"
        calls: list[CallRecord] = []
        events: list[TranscriptEvent] = []
        tool_calls: list[ToolCallRecord] = []
        trial = TrialResult(scenario_id=scenario.id, category=scenario.category, tags=scenario.tags, trial_index=k)
        started = time.perf_counter()
        with tracer.start_as_current_span("trial") as span:
            span.set_attribute("arbiter.scenario", scenario.id)
            span.set_attribute("arbiter.trial", k)
            span.set_attribute("arbiter.run", self.run_id)
            trial.trace_id = format(span.get_span_context().trace_id, "032x")
            state = self.env_cls.build_state(scenario.snapshot, scenario.patch)
            env = self.env_cls.from_state(state, faults=scenario.faults)
            initial = env.dump_state()
            deps = AgentDeps(llm=self.llm, prompts_dir=self.prompts_dir, extra={"environment": self.env_cls.name})
            tools = env.tool_specs(descriptions=self.tool_descriptions, retrieval=self.config.agent.retrieval)
            history: list[Message] = []
            env.conversation = history
            agent = None
            try:
                agent = create_agent(self.config.agent, deps)
                trial.termination = "turn_limit"
                for turn in range(scenario.user.max_turns):
                    with tracer.start_as_current_span("user_turn"):
                        ut = await self.user.next(scenario.user, history, trial_key=trial_key, on_call=calls.append)
                    final_turn = ut.status != "continue"
                    if not ut.message or (final_turn and ut.status == "give_up"):
                        trial.termination = "give_up" if ut.status == "give_up" else "done"
                        break
                    # A user who says "yes, book it, thanks!" and ends in the same breath still expects the agent
                    # to act on it, so the closing message is delivered before the conversation ends.
                    history.append(Message(role="user", content=ut.message))
                    events.append(TranscriptEvent(kind="user", turn=turn, content=ut.message,
                                                  t_ms=_ms(started)))
                    ctx = TurnContext(env=env, messages=history, tools=tools, turn=turn, trial_key=trial_key,
                                      llm=self.llm, on_call=calls.append, events=events, tool_calls=tool_calls,
                                      started=started)
                    with tracer.start_as_current_span("agent_turn") as aspan:
                        aspan.set_attribute("arbiter.turn", turn)
                        reply = await agent.respond(ctx)
                    history.append(Message(role="assistant", content=reply))
                    events.append(TranscriptEvent(kind="assistant", turn=turn, content=reply, t_ms=_ms(started)))
                    trial.turns = turn + 1
                    if final_turn:
                        trial.termination = "done"
                        break
            except BudgetExceeded as exc:
                self._abort = f"budget: {exc}"
                _fail(trial, events, f"budget exceeded: {exc}")
            except CassetteMiss as exc:
                _fail(trial, events, f"replay miss (behaviour drifted from recording): {exc}")
            except Exception as exc:  # an agent crash is a result to record, not a reason to stop the run
                _fail(trial, events, f"{type(exc).__name__}: {exc}")
            finally:
                if agent is not None:
                    await agent.aclose()
            final = env.dump_state()
            trial.events, trial.tool_calls, trial.calls = events, tool_calls, calls
            trial.rule_events, trial.approvals = list(env.rule_events), list(env.approvals)
            trial.state_diff = state_diff(initial, final)
            ctx_checks = CheckContext(
                scenario_id=scenario.id, env=env, initial_state=initial, final_state=final, tool_calls=tool_calls,
                events=events, rule_events=env.rule_events, approvals=env.approvals,
                user_knowledge=scenario.user.knowledge_text(),
            )
            trial.checks = await self._evaluate(scenario, ctx_checks, trial, trial_key, calls)
            trial.success = trial.status == "completed" and all(c.passed for c in trial.checks if c.required)
            span.set_attribute("arbiter.success", trial.success)
        trial.trace = collector.pop(trial.trace_id)
        return trial

    async def _evaluate(self, scenario: Scenario, ctx: CheckContext, trial: TrialResult, trial_key: str,
                        calls: list[CallRecord]) -> list[CheckResult]:
        results: list[CheckResult] = []
        for check in scenario.checks:
            if isinstance(check, JudgeCheck):
                if trial.status != "completed" or not self.judge or not self.config.judge.enabled:
                    continue
                try:
                    results += await self.judge.grade(ctx.events, check.rubric, check.criteria,
                                                      goal=scenario.user.goal, trial_key=trial_key,
                                                      required=check.required, on_call=calls.append)
                except (BudgetExceeded, CassetteMiss) as exc:
                    results.append(CheckResult(name=f"judge:{check.rubric}", type="judge", kind="judge",
                                               passed=False, required=False, detail=f"judge unavailable: {exc}"))
                continue
            try:
                results.append(check.evaluate(ctx))
            except Exception as exc:
                results.append(CheckResult(name=check.label(), type=check.type, kind=check.kind, passed=False,
                                           required=check.required, detail=f"check crashed: {exc}"))
        return results


def _ms(started: float) -> float:
    return round((time.perf_counter() - started) * 1000, 1)


def _fail(trial: TrialResult, events: list[TranscriptEvent], msg: str) -> None:
    trial.status, trial.error, trial.termination = "error", msg, "error"
    events.append(TranscriptEvent(kind="error", turn=trial.turns, content=msg))


def _aborted_trial(s: Scenario, k: int, reason: str) -> TrialResult:
    return TrialResult(scenario_id=s.id, category=s.category, tags=s.tags, trial_index=k, status="error",
                       error=f"skipped: run aborted ({reason})", termination="error")


def new_run_id(name: str) -> str:
    stamp = datetime.now(UTC).strftime("%Y%m%d-%H%M%S")
    return f"{stamp}-{name}-{uuid.uuid4().hex[:4]}"


def _git_sha() -> str | None:
    try:
        return subprocess.run(["git", "rev-parse", "--short", "HEAD"], capture_output=True, text=True,
                              timeout=5).stdout.strip() or None
    except Exception:
        return None
