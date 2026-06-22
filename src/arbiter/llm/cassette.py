from __future__ import annotations

import json
import os
import threading
from enum import StrEnum
from pathlib import Path

from arbiter.llm.types import ChatResponse


class CassetteMode(StrEnum):
    LIVE = "live"
    RECORD = "record"
    REPLAY = "replay"
    CACHE = "cache"


class CassetteMiss(RuntimeError):
    """Replay mode found no recorded response. Replay never falls through to a live call."""


class Cassette:
    def __init__(self, path: str | Path | None, mode: CassetteMode = CassetteMode.LIVE):
        self.mode = CassetteMode(mode)
        self.path = Path(path) if path else None
        self._lock = threading.Lock()
        self._entries: dict[str, dict] = {}
        self._dirty = False
        if self.mode in (CassetteMode.REPLAY, CassetteMode.CACHE, CassetteMode.RECORD) and self.path is None:
            raise ValueError(f"cassette mode {self.mode} needs a cassette path")
        if self.path and self.path.exists() and self.mode != CassetteMode.LIVE:
            self._entries = json.loads(self.path.read_text())
        elif self.mode == CassetteMode.REPLAY:
            raise FileNotFoundError(f"replay cassette not found: {self.path}")

    def __len__(self) -> int:
        return len(self._entries)

    def lookup(self, key: str) -> ChatResponse | None:
        if self.mode in (CassetteMode.LIVE, CassetteMode.RECORD):
            return None
        entry = self._entries.get(key)
        if entry is None:
            if self.mode == CassetteMode.REPLAY:
                raise CassetteMiss(f"no recorded response for request {key[:12]} in {self.path}")
            return None
        resp = ChatResponse.model_validate(entry)
        return resp.model_copy(update={"from_cassette": True})

    def store(self, key: str, response: ChatResponse) -> None:
        if self.mode not in (CassetteMode.RECORD, CassetteMode.CACHE):
            return
        with self._lock:
            self._entries[key] = response.model_dump(mode="json", exclude={"from_cassette"})
            self._dirty = True

    def flush(self) -> None:
        if not self._dirty or not self.path:
            return
        with self._lock:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.path.with_suffix(".tmp")
            tmp.write_text(json.dumps(self._entries, sort_keys=True, separators=(",", ":")))
            os.replace(tmp, self.path)
            self._dirty = False
