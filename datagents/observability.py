"""A13: Ingestion observability -- per-tool spans and metrics.

Deliberately separate from recon_platform.observability.tracer.GraphTracer
(C7): that tracer captures one span per graph NODE via LangChain callbacks,
which is too coarse for what A13 actually asks for -- per SOURCE TOOL
metrics (which tool, how many rows in/out, how many retry attempts). Rather
than modify Khyati's tracer.py to special-case ingestion internals it has
no visibility into, this stays a plain, framework-independent record that
ingestion_agent attaches to state as "ingestion_metrics". C7's tracer still
captures the single "ingestion" node span same as before; this is the
finer-grained detail nested logically inside that span, surfaced through
state rather than through LangChain's callback system.
"""
from __future__ import annotations

import time
from contextlib import contextmanager
from dataclasses import asdict, dataclass


@dataclass
class ToolSpan:
    """One source-tool call's observability record."""

    source_name: str
    source_type: str
    rows_in: int = 0
    rows_out: int = 0
    issues_out: int = 0
    retry_attempts: int = 1
    duration_ms: float = 0.0
    status: str = "ok"

    def as_dict(self) -> dict:
        return asdict(self)


@contextmanager
def timed():
    """Yields a mutable box; box['ms'] holds elapsed time once the with-block exits."""
    start = time.perf_counter()
    box = {"ms": 0.0}
    try:
        yield box
    finally:
        box["ms"] = (time.perf_counter() - start) * 1000
