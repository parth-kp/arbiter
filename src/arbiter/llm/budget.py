from __future__ import annotations

import json
import os
import threading
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path


class BudgetExceeded(RuntimeError):
    pass


class SpendLedger:
    """Persistent record of every dollar spent on live calls, enforced before each call.

    Before a call we reserve a worst-case estimate; afterwards we settle to the actual cost. Because
    reservations count against the cap, parallel trials cannot collectively overshoot it.
    """

    def __init__(self, path: str | Path | None, cap_usd: float):
        self.path = Path(path) if path else None
        self.cap_usd = cap_usd
        self._lock = threading.Lock()
        self._reserved = 0.0
        self._data: dict = {"cap_usd": cap_usd, "total_usd": 0.0, "runs": {}}
        if self.path and self.path.exists():
            self._data = json.loads(self.path.read_text())
            self._data["cap_usd"] = cap_usd

    @property
    def total_usd(self) -> float:
        return float(self._data["total_usd"])

    @property
    def reserved_usd(self) -> float:
        return self._reserved

    def reserve(self, amount: float, run_budget: RunBudget | None = None) -> None:
        with self._lock:
            if self.total_usd + self._reserved + amount > self.cap_usd:
                raise BudgetExceeded(
                    f"global cap ${self.cap_usd:.2f} would be exceeded "
                    f"(spent ${self.total_usd:.4f}, reserved ${self._reserved:.4f}, next call up to ${amount:.4f})"
                )
            if run_budget is not None:
                run_budget._reserve(amount)
            self._reserved += amount

    def settle(self, reserved: float, actual: float, run_id: str, model: str, provider: str,
               run_budget: RunBudget | None = None) -> None:
        with self._lock:
            self._reserved = max(0.0, self._reserved - reserved)
            if run_budget is not None:
                run_budget._settle(reserved, actual)
            self._data["total_usd"] = round(self.total_usd + actual, 8)
            run = self._data["runs"].setdefault(
                run_id, {"cost_usd": 0.0, "calls": 0, "by_model": {}, "by_provider": {}, "started": _now()}
            )
            run["cost_usd"] = round(run["cost_usd"] + actual, 8)
            run["calls"] += 1
            run["by_model"][model] = round(run["by_model"].get(model, 0.0) + actual, 8)
            run["by_provider"][provider] = run["by_provider"].get(provider, 0) + 1
            run["updated"] = _now()
            self._save()

    def release(self, reserved: float, run_budget: RunBudget | None = None) -> None:
        with self._lock:
            self._reserved = max(0.0, self._reserved - reserved)
            if run_budget is not None:
                run_budget._settle(reserved, 0.0)

    def _save(self) -> None:
        if not self.path:
            return
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(self._data, indent=2, sort_keys=True))
        os.replace(tmp, self.path)


@dataclass
class RunBudget:
    cap_usd: float
    spent_usd: float = 0.0
    reserved_usd: float = 0.0
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    def _reserve(self, amount: float) -> None:
        if self.spent_usd + self.reserved_usd + amount > self.cap_usd:
            raise BudgetExceeded(
                f"run cap ${self.cap_usd:.2f} would be exceeded (spent ${self.spent_usd:.4f}, "
                f"reserved ${self.reserved_usd:.4f}, next call up to ${amount:.4f})"
            )
        self.reserved_usd += amount

    def _settle(self, reserved: float, actual: float) -> None:
        self.reserved_usd = max(0.0, self.reserved_usd - reserved)
        self.spent_usd += actual


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")
