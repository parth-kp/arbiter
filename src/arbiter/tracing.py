from __future__ import annotations

import base64
import os
import threading
from collections import defaultdict
from typing import Any

from opentelemetry import trace
from opentelemetry.sdk.trace import ReadableSpan, SpanProcessor, TracerProvider

_configured = False
_lock = threading.Lock()


class LocalSpanCollector(SpanProcessor):
    """Keeps finished spans grouped by trace id so each trial can store its own trace."""

    def __init__(self) -> None:
        self._spans: dict[str, list[dict[str, Any]]] = defaultdict(list)
        self._lock = threading.Lock()

    def on_end(self, span: ReadableSpan) -> None:
        ctx = span.get_span_context()
        tid = format(ctx.trace_id, "032x")
        parent = format(span.parent.span_id, "016x") if span.parent else None
        with self._lock:
            self._spans[tid].append({
                "name": span.name,
                "span_id": format(ctx.span_id, "016x"),
                "parent_id": parent,
                "start_ns": span.start_time,
                "duration_ms": round(((span.end_time or 0) - (span.start_time or 0)) / 1e6, 3),
                "attributes": {k: v for k, v in (span.attributes or {}).items()},
            })

    def pop(self, trace_id: str) -> list[dict[str, Any]]:
        with self._lock:
            spans = self._spans.pop(trace_id, [])
        base = min((s["start_ns"] for s in spans), default=0)
        for s in spans:
            s["offset_ms"] = round((s.pop("start_ns") - base) / 1e6, 3)
        return sorted(spans, key=lambda s: s["offset_ms"])

    def shutdown(self) -> None:
        return None

    def force_flush(self, timeout_millis: int = 30000) -> bool:
        return True


collector = LocalSpanCollector()


def langfuse_configured() -> bool:
    return all(os.environ.get(k) for k in ("LANGFUSE_PUBLIC_KEY", "LANGFUSE_SECRET_KEY", "LANGFUSE_HOST"))


def setup_tracing() -> None:
    global _configured
    with _lock:
        if _configured:
            return
        provider = TracerProvider()
        provider.add_span_processor(collector)
        if langfuse_configured():
            from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
            from opentelemetry.sdk.trace.export import BatchSpanProcessor

            host = os.environ["LANGFUSE_HOST"].rstrip("/")
            token = base64.b64encode(
                f"{os.environ['LANGFUSE_PUBLIC_KEY']}:{os.environ['LANGFUSE_SECRET_KEY']}".encode()
            ).decode()
            exporter = OTLPSpanExporter(endpoint=f"{host}/api/public/otel/v1/traces",
                                        headers={"Authorization": f"Basic {token}"})
            provider.add_span_processor(BatchSpanProcessor(exporter))
        trace.set_tracer_provider(provider)
        _configured = True


def trace_url(trace_id: str) -> str:
    """Langfuse deep link when configured, otherwise the dashboard's local trace view."""
    if langfuse_configured():
        return f"{os.environ['LANGFUSE_HOST'].rstrip('/')}/trace/{trace_id}"
    return f"/traces/{trace_id}"
