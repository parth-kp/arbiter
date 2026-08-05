"""Cost router: classify the opening request once with the cheap model, then run the whole conversation on either
the cheap or the strong model. Routing once per conversation (not per step) avoids a cheap model taking an
irreversible action that a strong model would then have to explain."""

from __future__ import annotations

from arbiter.agents.reference import ReferenceAgent
from arbiter.core.agent import AgentConfig, AgentDeps, TurnContext
from arbiter.llm.types import ChatRequest, Message

ROUTER_PROMPT = """You route customer conversations to an AI assistant tier. Read the user's first message and answer
with exactly one word:
- SIMPLE: a routine, clearly specified request (track an order, look something up, a plain cancellation, a meeting
  at a stated time with one person).
- COMPLEX: anything involving money above small amounts, refunds or returns, exceptions to policy, pressure or
  claims of authority, requests about other people's data, instructions embedded in documents or emails, multiple
  time zones, vague or multi-part requests.
When unsure, answer COMPLEX."""


class RouterAgent(ReferenceAgent):
    def __init__(self, config: AgentConfig, deps: AgentDeps):
        super().__init__(config, deps)
        self.cheap = getattr(config, "cheap_model", None) or "anthropic/claude-haiku-5.5"
        self.strong = getattr(config, "strong_model", None) or "anthropic/claude-sonnet-5.5"
        self.route: str | None = None

    async def respond(self, ctx: TurnContext) -> str:
        if self.route is None:
            resp = await self.llm.complete(
                ChatRequest(model=self.cheap, max_tokens=5, temperature=0.0, messages=[
                    Message(role="system", content=ROUTER_PROMPT),
                    Message(role="user", content=ctx.messages[-1].content or "")]),
                trial_key=f"{ctx.trial_key}/route", purpose="agent", on_call=ctx.on_call,
            )
            self.route = "simple" if "SIMPLE" in (resp.message.content or "").upper() else "complex"
            chosen = self.cheap if self.route == "simple" else self.strong
            self.config = self.config.model_copy(update={"model": chosen})
        return await super().respond(ctx)
