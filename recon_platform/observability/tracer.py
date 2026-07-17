"""Local tracer for graph observability using LangChain's callback system.

Attaching this as a callback (config={"callbacks": [tracer]}) when invoking
the graph captures a span per node, and per LLM call if a node makes one,
with zero changes needed to build_graph() or the node functions themselves.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any

from langchain_core.callbacks import BaseCallbackHandler


@dataclass
class Span:
    span_id: str
    parent_id: str | None
    name: str
    kind: str
    start_time: float
    end_time: float | None = None
    prompt_tokens: int = 0
    completion_tokens: int = 0
    status: str = "running"

    @property
    def duration_ms(self) -> float | None:
        if self.end_time is None:
            return None
        return (self.end_time - self.start_time) * 1000


class GraphTracer(BaseCallbackHandler):
    """Records a span per graph node (and per LLM call) for a single run."""

    def __init__(self) -> None:
        self.spans: dict[str, Span] = {}

    def on_chain_start(self, serialized, inputs, *, run_id, parent_run_id=None, tags=None, metadata=None, **kwargs):
        name = (metadata or {}).get("langgraph_node") or (serialized or {}).get("name") or "chain"
        self.spans[str(run_id)] = Span(
            span_id=str(run_id),
            parent_id=str(parent_run_id) if parent_run_id else None,
            name=name,
            kind="node",
            start_time=time.perf_counter(),
        )

    def on_chain_end(self, outputs, *, run_id, **kwargs):
        span = self.spans.get(str(run_id))
        if span is not None:
            span.end_time = time.perf_counter()
            span.status = "ok"

    def on_chain_error(self, error, *, run_id, **kwargs):
        span = self.spans.get(str(run_id))
        if span is not None:
            span.end_time = time.perf_counter()
            span.status = "error"

    def on_llm_start(self, serialized, prompts, *, run_id, parent_run_id=None, **kwargs):
        self.spans[str(run_id)] = Span(
            span_id=str(run_id),
            parent_id=str(parent_run_id) if parent_run_id else None,
            name=(serialized or {}).get("name", "llm"),
            kind="llm",
            start_time=time.perf_counter(),
        )

    def on_llm_end(self, response, *, run_id, **kwargs):
        span = self.spans.get(str(run_id))
        if span is None:
            return
        span.end_time = time.perf_counter()
        span.status = "ok"
        usage = getattr(response, "llm_output", None) or {}
        token_usage = usage.get("token_usage", {})
        span.prompt_tokens = token_usage.get("prompt_tokens", 0)
        span.completion_tokens = token_usage.get("completion_tokens", 0)

    def node_spans(self) -> list[Span]:
        return [s for s in self.spans.values() if s.kind == "node"]

    def total_tokens(self) -> int:
        return sum(s.prompt_tokens + s.completion_tokens for s in self.spans.values())

    def trace_tree(self) -> list[dict[str, Any]]:
        """Return spans nested by parent_id, root spans first."""
        by_parent: dict[str | None, list[Span]] = {}
        for span in self.spans.values():
            by_parent.setdefault(span.parent_id, []).append(span)

        def build(parent_id: str | None) -> list[dict[str, Any]]:
            children = sorted(by_parent.get(parent_id, []), key=lambda s: s.start_time)
            return [
                {
                    "name": s.name,
                    "kind": s.kind,
                    "duration_ms": s.duration_ms,
                    "status": s.status,
                    "children": build(s.span_id),
                }
                for s in children
            ]

        return build(None)
