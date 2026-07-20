"""Minimal text-based trace viewer.

Prints the span tree captured by a GraphTracer in an indented, readable
format. This is the "trace viewer" for now; swapping in a real UI later
just means rendering tracer.trace_tree() differently, the tracer itself
doesn't need to change.
"""

from __future__ import annotations

from recon_platform.observability.tracer import GraphTracer


def print_trace(tracer: GraphTracer) -> None:
    def _print(nodes: list[dict], depth: int = 0) -> None:
        for node in nodes:
            duration = f"{node['duration_ms']:.1f}ms" if node["duration_ms"] is not None else "n/a"
            print(f"{'  ' * depth}- {node['name']} ({node['kind']}) [{node['status']}] {duration}")
            _print(node["children"], depth + 1)

    _print(tracer.trace_tree())
