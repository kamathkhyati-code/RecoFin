"""C13: E2E baseline metrics.

Runs the real graph end to end on golden data, captures auto-match rate,
exception count, latency, and token cost, and writes a versioned
baseline report using C9's report writer (reused, not reinvented).
"""

from __future__ import annotations

import time
from typing import Any

from recon_platform.eval.report import write_report
from recon_platform.graph.build import build_graph
from recon_platform.observability.tracer import GraphTracer


def run_baseline(
    initial_state: dict[str, Any],
    output_dir: str,
    run_label: str | None = None,
) -> tuple[str, str]:
    """Run the real graph E2E on golden data and write a baseline metrics report.

    run_label defaults to the run's own run_id, so distinct runs produce
    distinct, non-overwriting report files (write_report's generated_at
    timestamp inside each provides recency ordering).

    Returns (json_path, md_path).
    """
    graph = build_graph()
    tracer = GraphTracer()

    start = time.perf_counter()
    result = graph.invoke(initial_state, config={"callbacks": [tracer]})
    latency_ms = (time.perf_counter() - start) * 1000

    report = result["report"]
    label = run_label or f"baseline_{report.run_id}"

    metrics = {
        "run_id": report.run_id,
        "period": report.period,
        "matched_count": report.matched_count,
        "unmatched_count": report.unmatched_count,
        "exception_count": report.exception_count,
        "auto_match_rate": report.match_rate,
        "close_ready": report.close_ready,
        "latency_ms": round(latency_ms, 2),
        "node_count": len(tracer.node_spans()),
        "total_tokens": tracer.total_tokens(),
    }

    return write_report(metrics, output_dir, label)
