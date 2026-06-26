from __future__ import annotations

import math
import re
from collections import Counter

from pydantic import BaseModel

_WORD = re.compile(r"[a-z0-9$]+")


class PolicyDoc(BaseModel):
    id: str
    title: str
    text: str


def _tokens(text: str) -> list[str]:
    return [t for t in _WORD.findall(text.lower()) if len(t) > 1]


class PolicyIndex:
    """BM25 over policy sections. Small, dependency-free and deterministic, which keeps replay exact."""

    def __init__(self, docs: list[PolicyDoc], k1: float = 1.5, b: float = 0.75):
        self.chunks: list[dict[str, str]] = []
        for doc in docs:
            for section in re.split(r"\n(?=#{1,3} )", doc.text):
                section = section.strip()
                if section:
                    heading = section.splitlines()[0].lstrip("# ").strip()
                    self.chunks.append({"doc": doc.id, "section": heading, "text": section})
        self.k1, self.b = k1, b
        self._tf = [Counter(_tokens(c["text"])) for c in self.chunks]
        self._len = [sum(tf.values()) for tf in self._tf]
        self._avg = (sum(self._len) / len(self._len)) if self._len else 0.0
        df: Counter[str] = Counter()
        for tf in self._tf:
            df.update(tf.keys())
        n = len(self.chunks)
        self._idf = {t: math.log(1 + (n - d + 0.5) / (d + 0.5)) for t, d in df.items()}

    def search(self, query: str, k: int = 3) -> list[dict[str, str]]:
        q = _tokens(query)
        scored = []
        for i, tf in enumerate(self._tf):
            s = 0.0
            for t in q:
                if t in tf:
                    f = tf[t]
                    norm = self.k1 * (1 - self.b + self.b * self._len[i] / self._avg)
                    s += self._idf[t] * f * (self.k1 + 1) / (f + norm)
            if s > 0:
                scored.append((s, i))
        scored.sort(key=lambda x: (-x[0], x[1]))
        return [self.chunks[i] for _, i in scored[:k]]
