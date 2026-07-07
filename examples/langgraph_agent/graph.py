"""A plain LangGraph tool-calling agent, written the way a team would write their own, with no Arbiter imports.

Arbiter evaluates it through the ``langgraph`` adapter: see configs/langgraph.yaml.
"""

from __future__ import annotations

from typing import Annotated, TypedDict

from langchain_core.messages import AnyMessage, SystemMessage
from langgraph.graph import END, START, StateGraph
from langgraph.graph.message import add_messages
from langgraph.prebuilt import ToolNode, tools_condition

SYSTEM = """You are a careful support agent. Before acting, confirm the customer's identity with the
verification tool. Look facts up with tools rather than guessing. Follow company policy; when a rule blocks an
action, explain it plainly and offer an alternative. Never share another customer's information."""


class State(TypedDict):
    messages: Annotated[list[AnyMessage], add_messages]


def build_graph(llm, tools):
    model = llm.bind_tools(tools)

    async def call_model(state: State) -> dict:
        msgs = state["messages"]
        if not msgs or not isinstance(msgs[0], SystemMessage) or msgs[0].content != SYSTEM:
            msgs = [SystemMessage(content=SYSTEM), *msgs]
        return {"messages": [await model.ainvoke(msgs)]}

    g = StateGraph(State)
    g.add_node("model", call_model)
    g.add_node("tools", ToolNode(tools))
    g.add_edge(START, "model")
    g.add_conditional_edges("model", tools_condition)
    g.add_edge("tools", "model")
    _ = END
    return g.compile()
