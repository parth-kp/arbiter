"""Evaluate a LangGraph agent you built yourself.

Set ``agent.graph: "your_module:build_graph"`` where ``build_graph(llm, tools)`` returns a compiled graph whose
state has a ``messages`` list. Arbiter supplies a ``ChatOpenAI`` whose HTTP traffic is served by Arbiter's LLM
layer (record/replay, budget) and LangChain tools that execute against the environment.
"""

from __future__ import annotations

import httpx

from arbiter.agents.openai_shim import ArbiterTransport
from arbiter.core.agent import Agent, AgentConfig, AgentDeps, TurnContext, reasoning_param
from arbiter.core.registry import import_object


class LangGraphAgent(Agent):
    def __init__(self, config: AgentConfig, deps: AgentDeps):
        super().__init__(config)
        from langchain_openai import ChatOpenAI

        graph_path = getattr(config, "graph", None)
        if not graph_path:
            raise ValueError("langgraph agent needs agent.graph: 'module:build_graph'")
        self.build_graph = import_object(graph_path)
        self.transport = ArbiterTransport(deps.llm, reasoning_param(config.reasoning_max_tokens))
        self.llm = ChatOpenAI(
            model=config.model, api_key="arbiter-shim", base_url="http://arbiter.shim/v1",
            temperature=config.temperature, max_tokens=config.max_tokens, max_retries=0,
            http_async_client=httpx.AsyncClient(transport=self.transport),
        )
        self.graph = None
        self.messages: list = []
        self._ctx: TurnContext | None = None

    def _tools(self, ctx: TurnContext):
        from langchain_core.tools import StructuredTool

        def make(name: str):
            def run(**kwargs):
                assert self._ctx is not None
                return self._ctx.call_tool(name, kwargs).as_text()

            return run

        return [StructuredTool.from_function(func=make(t.name), name=t.name, description=t.description,
                                             args_schema=t.parameters) for t in ctx.tools]

    async def respond(self, ctx: TurnContext) -> str:
        from langchain_core.messages import AIMessage, HumanMessage, SystemMessage

        self._ctx = ctx
        self.transport.bind(ctx.trial_key, ctx.on_call)
        if self.graph is None:
            self.graph = self.build_graph(self.llm, self._tools(ctx))
            if ctx.system_context:
                self.messages.append(SystemMessage(content=ctx.system_context))
        self.messages.append(HumanMessage(content=ctx.messages[-1].content or ""))
        state = await self.graph.ainvoke({"messages": self.messages},
                                         config={"recursion_limit": 2 * self.config.max_tool_steps + 2})
        self.messages = list(state["messages"])
        for m in reversed(self.messages):
            if isinstance(m, AIMessage) and not m.tool_calls:
                return m.content if isinstance(m.content, str) else str(m.content)
        return ""
