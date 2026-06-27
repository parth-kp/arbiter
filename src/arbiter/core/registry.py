from __future__ import annotations

import importlib
from importlib.metadata import entry_points

from arbiter.core.environment import Environment

_ENVIRONMENTS: dict[str, type[Environment]] = {}


def register_environment(cls: type[Environment]) -> type[Environment]:
    _ENVIRONMENTS[cls.name] = cls
    return cls


def _load_entry_points() -> None:
    for ep in entry_points(group="arbiter.environments"):
        if ep.name in _ENVIRONMENTS:
            continue
        try:
            cls = ep.load()
        except ImportError:
            continue
        _ENVIRONMENTS[ep.name] = cls


def import_object(path: str):
    module, _, attr = path.partition(":")
    obj = importlib.import_module(module)
    for part in attr.split(".") if attr else []:
        obj = getattr(obj, part)
    return obj


def get_environment(name: str) -> type[Environment]:
    """Resolve an environment by registered name or by ``package.module:ClassName``."""
    if ":" in name:
        return import_object(name)
    if name not in _ENVIRONMENTS:
        _load_entry_points()
    if name not in _ENVIRONMENTS:
        raise KeyError(f"unknown environment {name!r}; known: {sorted(list_environments())}")
    return _ENVIRONMENTS[name]


def list_environments() -> dict[str, type[Environment]]:
    _load_entry_points()
    return dict(_ENVIRONMENTS)
