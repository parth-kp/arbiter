# Extending Arbiter

This guide covers the four extension points, each with code you can copy:

1. [Add an environment](#1-add-an-environment): one Python module plus fixtures
2. [Add scenarios](#2-add-scenarios): YAML, version-controlled
3. [Add a check type](#3-add-a-check-type): a small Pydantic class
4. [Add an agent adapter](#4-add-an-agent-adapter): to evaluate an agent Arbiter didn't build

The example builds a **meeting-room booking** environment from scratch. Every code block that starts with
`# file:` is extracted and run by `tests/test_extending_guide.py`, so the guide can't drift from the code without CI
failing.

---

## 1. Add an environment

An environment is a subclass of `arbiter.core.environment.Environment` with four parts:

| Part | How |
|---|---|
| **State**, snapshotted and reset per trial | a Pydantic model (`State`) loaded from `fixtures/<snapshot>.yaml`. Use dicts keyed by id so scenarios can patch them. |
| **Typed tools** | methods decorated with `@tool`, each taking one Pydantic argument model. The docstring is the tool description. |
| **Business rules, enforced in code** | raise `RuleViolation(rule, message)` inside a tool. The action is blocked, the agent sees the message, and the attempt is recorded. Raise `ToolError` for ordinary failures like "not found". |
| **Policy documents** for retrieval | markdown files in `fixtures/policies/`, searchable through `self.policy_search(query)` |

Every trial builds a fresh environment from the snapshot, so trials are deterministic and isolated. Never read the
wall clock or a random generator inside an environment; keep "now" in the state.

```python
# file: rooms_env/__init__.py
from pathlib import Path

from pydantic import BaseModel, Field

from arbiter.core.environment import Environment, RuleViolation, ToolError, predicate, tool


class Room(BaseModel):
    id: str
    name: str
    seats: int


class Booking(BaseModel):
    id: str
    room_id: str
    start_hour: int
    end_hour: int
    owner: str


class RoomsState(BaseModel):
    rooms: dict[str, Room]
    bookings: dict[str, Booking] = Field(default_factory=dict)
    next_id: int = 1


class FindArgs(BaseModel):
    min_seats: int = Field(ge=1)


class BookArgs(BaseModel):
    room_id: str
    start_hour: int = Field(ge=0, le=23)
    end_hour: int = Field(ge=1, le=24)
    owner: str


class PolicyArgs(BaseModel):
    query: str


class RoomsEnvironment(Environment):
    name = "rooms"
    description = "Book meeting rooms for the day."
    State = RoomsState
    fixtures_dir = Path(__file__).parent / "fixtures"
    MAX_HOURS = 3

    @tool()
    def find_rooms(self, args: FindArgs) -> list[dict]:
        """List rooms with at least `min_seats` seats."""
        return [r.model_dump() for r in self.state.rooms.values() if r.seats >= args.min_seats]

    @tool(mutates=True)
    def book_room(self, args: BookArgs) -> dict:
        """Book a room from start_hour to end_hour (24h clock, today)."""
        if args.room_id not in self.state.rooms:
            raise ToolError(f"no room {args.room_id}")
        if args.end_hour <= args.start_hour:
            raise ToolError("end_hour must be after start_hour")
        if args.end_hour - args.start_hour > self.MAX_HOURS:
            raise RuleViolation("max_duration", f"bookings are limited to {self.MAX_HOURS} hours")
        for b in self.state.bookings.values():
            if b.room_id == args.room_id and args.start_hour < b.end_hour and b.start_hour < args.end_hour:
                raise RuleViolation("double_booking", f"{args.room_id} is taken {b.start_hour}:00-{b.end_hour}:00")
        bid = f"BK{self.state.next_id}"
        self.state.next_id += 1
        self.state.bookings[bid] = Booking(id=bid, room_id=args.room_id, start_hour=args.start_hour,
                                           end_hour=args.end_hour, owner=args.owner)
        return {"booking_id": bid}

    @tool(retrieval=True)
    def search_policies(self, args: PolicyArgs) -> list[dict]:
        """Search the room-booking policy."""
        return self.policy_search(args.query)

    @predicate()
    def room_booked(self, room_id: str, start_hour: int) -> tuple[bool, str]:
        hits = [b.id for b in self.state.bookings.values() if b.room_id == room_id and b.start_hour == start_hour]
        return bool(hits), f"bookings of {room_id} at {start_hour}: {hits}"


environment = RoomsEnvironment
```

```yaml
# file: rooms_env/fixtures/default.yaml
rooms:
  R1: {id: R1, name: Fjord, seats: 4}
  R2: {id: R2, name: Glacier, seats: 12}
bookings:
  BK0: {id: BK0, room_id: R2, start_hour: 9, end_hour: 11, owner: ops}
```

```markdown
# file: rooms_env/fixtures/policies/booking.md
# Duration
Rooms can be booked for at most three hours at a time.

# Double booking
A room cannot be booked twice for overlapping times.
```

Register the environment so `--env rooms` works. Add an entry point in your package's `pyproject.toml`:

```toml
[project.entry-points."arbiter.environments"]
rooms = "rooms_env:environment"
```

Without an entry point, you can always refer to it by import path: `--env rooms_env:RoomsEnvironment`.

**Test the rules by calling tools directly**, with no model involved. These tests prove a rule holds whatever an
agent does:

```python
# file: tests/test_rooms_rules.py
from rooms_env import RoomsEnvironment


def fresh():
    return RoomsEnvironment.from_state(RoomsEnvironment.build_state())


def test_double_booking_is_blocked_and_recorded():
    env = fresh()
    r = env.call_tool("book_room", {"room_id": "R2", "start_hour": 10, "end_hour": 12, "owner": "me"})
    assert not r.ok and r.rule == "double_booking"
    assert env.rule_events[0].rule == "double_booking"
    assert len(env.dump_state()["bookings"]) == 1


def test_bad_arguments_get_a_readable_error():
    r = fresh().call_tool("book_room", {"room_id": "R1"})
    assert not r.ok and r.error_kind == "validation" and "start_hour" in r.error
```

## 2. Add scenarios

Scenarios live in `scenarios/<environment>/*.yaml`. A file may hold one scenario or a list of them.

```yaml
# file: scenarios/rooms/seeds.yaml
- id: rooms-book-standup
  environment: rooms
  category: happy_path
  golden: true
  tags: [booking]
  user:
    persona: Sam, an engineering manager.
    goal: Book a room for 10 people from 14:00 to 15:00 today for the team retro.
    knowledge: {owner_name: sam}
    cooperativeness: cooperative   # cooperative | terse | impatient | confused | adversarial
    max_turns: 6
  checks:
    - {type: predicate, predicate: room_booked, args: {room_id: R2, start_hour: 14}}
    - {type: state, path: bookings.BK0.end_hour, value: 11}
    - {type: must_call, tool: find_rooms}
    - {type: no_rule_attempts, required: false}

- id: rooms-too-long
  environment: rooms
  category: policy_edge
  patch: {bookings: {BK0: null}}        # start from the snapshot with BK0 deleted
  faults: [{tool: find_rooms, error: "directory timeout", times: 1}]
  user:
    persona: Robin, planning an all-day workshop.
    goal: Book the big room from 9:00 to 17:00.
    hidden: If told it is too long, accept 9:00-12:00 instead.
  checks:
    - {type: predicate, predicate: room_booked, args: {room_id: R2, start_hour: 9}}
    - {type: state, path: bookings, op: len_eq, value: 1}
```

Field reference:

| Field | Meaning |
|---|---|
| `snapshot` / `patch` | starting state: a fixture name (default `default`) plus a deep-merge patch, where `null` deletes a key |
| `faults` | tool failures injected for this trial (`times` = how many calls fail) |
| `user` | the simulated user: `persona`, `goal`, `knowledge` (shared when relevant), `hidden` (private instructions), `opening` (fixed first message), `cooperativeness`, `max_turns` |
| `checks` | see the [check reference](#check-reference); final-state checks should lead |
| `golden` | include in the frozen regression set used by `arbiter gate` |

Check your work before spending money:

```bash
arbiter scenarios validate rooms        # builds every snapshot; catches unknown tools, predicates and ids
arbiter scenarios generate rooms        # expands scenarios/rooms/templates/*.yaml into variations
arbiter run --env rooms --config configs/cheap.yaml --set golden --trials 3
```

**Templates for variations.** A template is a scenario with `{{placeholders}}` and a list of parameter sets.
`arbiter scenarios generate` expands it, validates every result, drops duplicates, and writes
`generated/generated.yaml` for you to review and prune.

```yaml
# file: scenarios/rooms/templates/sizes.yaml
template_id: rooms-sizes
params:
  - {sid: small, seats: 3, room: R1}
  - {sid: large, seats: 10, room: R2}
scenario:
  id: rooms-gen-{{sid}}
  environment: rooms
  category: happy_path
  user: {persona: An office worker., goal: "Book a room for {{seats}} people from 13:00 to 14:00."}
  checks:
    - {type: predicate, predicate: room_booked, args: {room_id: "{{room}}", start_hour: 13}}
```

### Check reference

| Type | Kind | What it asserts |
|---|---|---|
| `state` | final state | `path` (dotted, list indexes allowed) `op` `value`; ops: `eq ne gt gte lt lte in not_in contains not_contains len_eq exists absent matches` |
| `state_unchanged` | final state | a subtree (or everything) equals the starting snapshot |
| `predicate` | final state | an environment `@predicate` returns true (or `expect: false`) |
| `must_call` / `must_not_call` | tool call | a tool was (not) called successfully, optionally with matching `args` (case-insensitive strings, `{op, value}` operators) |
| `call_order` | tool call | first successful calls happened in this order |
| `arg_constraint` | tool call | every successful call satisfies `arg op value` |
| `max_tool_calls` | tool call | at most `max` calls (optionally of one tool) |
| `no_rule_attempts` | policy (attempt) | no business rule had to block anything. Counted as an *attempt*, not a violation. |
| `no_cross_account_leak` | policy | no other owner's `sensitive_values()` appear in what the agent said |
| `no_fabricated_amounts` | policy | every `$` amount the agent stated is grounded in tool output, policy or the user's words |
| `approval_required` | policy | calls above `threshold` went through `request_approval` instead of executing |
| `transcript` | transcript | regex `match` / `not_match` over assistant (or user) messages |
| `judge` | judge | LLM judge on rubric criteria. Use only for what cannot be checked mechanically. |

Every check takes `name` and `required` (default true; judge checks default to false). A trial succeeds when it
completed and every required check passed.

## 3. Add a check type

Subclass `Check`, give `type` a literal default, implement `evaluate`, and decorate it with `@register_check`.
`CheckContext` gives you the final and initial state, every tool call, the transcript, rule events, approvals and the
environment itself.

```python
# file: rooms_env/checks.py
from typing import ClassVar, Literal

from arbiter.checks import Check, CheckContext, CheckResult, register_check


@register_check
class MaxFailedToolCalls(Check):
    """The agent may hit at most `max` failing tool calls (validation errors, faults, not-found...)."""

    type: Literal["max_failed_tool_calls"] = "max_failed_tool_calls"
    kind: ClassVar[str] = "tool_call"
    max: int = 1

    def evaluate(self, ctx: CheckContext) -> CheckResult:
        failed = [c.tool for c in ctx.tool_calls if not c.ok and c.error_kind != "rule"]
        return self.result(len(failed) <= self.max, f"failed calls: {failed}")
```

Import the module before scenarios load (for example from your environment's `__init__.py`). Then
`{type: max_failed_tool_calls, max: 0}` works in any scenario, for any environment.

## 4. Add an agent adapter

There are four ways to put an agent under test. Tools are always executed by Arbiter, so business rules hold and
every action is recorded.

| Your agent is... | Use |
|---|---|
| any OpenAI-compatible chat model with tool calling | `agent: {type: openai, model: ..., base_url: ..., system_prompt: ...}` |
| a service with an HTTP endpoint | `agent: {type: http, endpoint: ...}` speaking [arbiter-agent/1](HTTP_PROTOCOL.md) |
| a LangGraph graph | `agent: {type: langgraph, graph: "your_module:build_graph"}`. See [`examples/langgraph_agent`](../examples/langgraph_agent/graph.py). |
| anything else in Python | subclass `Agent` (below) |

An `Agent` gets one `respond(ctx)` call per user turn. It reads `ctx.messages`, calls tools with `ctx.call_tool`,
and returns its reply. Use `ctx.llm` for model calls so they are recorded, replayable in CI and counted against the
budget. One instance is created per trial, so it can keep state between turns.

```python
# file: rooms_env/agent.py
from arbiter.core.agent import Agent, TurnContext


class GreedyBooker(Agent):
    """A rule-based agent: books the first room that fits for 14:00-15:00. No model needed."""

    async def respond(self, ctx: TurnContext) -> str:
        rooms = ctx.call_tool("find_rooms", {"min_seats": 10}).output or []
        if not rooms:
            return "No room is big enough."
        result = ctx.call_tool("book_room", {"room_id": rooms[0]["id"], "start_hour": 14, "end_hour": 15,
                                             "owner": "sam"})
        return f"Booked {rooms[0]['name']}." if result.ok else f"Could not book: {result.error}"
```

Run it from the CLI with `--agent rooms_env.agent:GreedyBooker`, or in Python:

```python
import arbiter
from rooms_env.agent import GreedyBooker

result = arbiter.evaluate("rooms", GreedyBooker, set="golden", trials=3)
print(result.summary["overall"]["success_rate"], result.summary["overall"]["pass^3"])
```

The simulated user still needs a model. Use `mode="replay"` with a recorded cassette to run with no key, as CI
does.

## Checklist for a new environment

- [ ] `Environment` subclass with `name`, `description`, `State`, `fixtures_dir`, and `environment = ...` at module level
- [ ] tools take one Pydantic model each, with useful docstrings
- [ ] every business rule raises `RuleViolation` with a stable rule name, and has a direct-call test
- [ ] `sensitive_values()` if the domain has data that must not leak across owners
- [ ] `system_context()` for facts the agent may know up front (current time, who it serves)
- [ ] fixtures keep "now" in the state; no wall clock, no randomness
- [ ] scenarios validate (`arbiter scenarios validate <env>`), and final-state checks lead
