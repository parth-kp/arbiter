from __future__ import annotations

from collections.abc import Callable

from arbiter.core.agent import Agent, AgentConfig, AgentDeps
from arbiter.core.registry import import_object


def _reference(config: AgentConfig, deps: AgentDeps) -> Agent:
    from arbiter.agents.reference import ReferenceAgent

    return ReferenceAgent(config, deps)


def _openai(config: AgentConfig, deps: AgentDeps) -> Agent:
    from arbiter.agents.openai_chat import OpenAIChatAgent

    return OpenAIChatAgent(config, deps)


def _http(config: AgentConfig, deps: AgentDeps) -> Agent:
    from arbiter.agents.http import HTTPAgent

    return HTTPAgent(config, deps)


def _langgraph(config: AgentConfig, deps: AgentDeps) -> Agent:
    from arbiter.agents.langgraph_adapter import LangGraphAgent

    return LangGraphAgent(config, deps)


AGENT_TYPES: dict[str, Callable[[AgentConfig, AgentDeps], Agent]] = {
    "reference": _reference,
    "openai": _openai,
    "http": _http,
    "langgraph": _langgraph,
}


def register_agent(name: str, factory: Callable[[AgentConfig, AgentDeps], Agent]) -> None:
    AGENT_TYPES[name] = factory


def create_agent(config: AgentConfig, deps: AgentDeps) -> Agent:
    """Build an agent by registered type or by ``package.module:ClassOrFactory``."""
    if config.type in AGENT_TYPES:
        return AGENT_TYPES[config.type](config, deps)
    if ":" in config.type:
        return import_object(config.type)(config, deps)
    raise KeyError(f"unknown agent type {config.type!r}; known: {sorted(AGENT_TYPES)} or module:Class")
