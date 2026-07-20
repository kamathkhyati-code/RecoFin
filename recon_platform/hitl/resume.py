"""HITL interrupt and resume API.

The graph interrupts right before the "resolution" node, which represents
an exception needing a human decision. An analyst's decision is injected
into state and the run resumes from the checkpoint.
"""

from __future__ import annotations

from recon_platform.graph.build import build_graph
from recon_platform.hitl.review_queue import review_queue


def build_hitl_graph(checkpointer):
    """Compile the graph so it pauses before the resolution (exception) node."""
    return build_graph(checkpointer=checkpointer, interrupt_before=["resolution"])


def start_run_with_hitl(graph, run_id: str, initial_state: dict) -> dict:
    """Start a run. If it pauses at the interrupt, register it on the review queue."""
    config = {"configurable": {"thread_id": run_id}}
    result = graph.invoke(initial_state, config=config)
    snapshot = graph.get_state(config)

    if "resolution" in snapshot.next:
        review_queue.add(run_id, reason="Unmatched items require analyst review.")

    return result


def resume_with_decision(graph, run_id: str, decision: dict) -> dict:
    """Resume API: inject an analyst's decision into state, then continue.

    decision is merged into the graph's state (e.g. {"unmatched_count": 0}
    to mark items as resolved) before execution continues from the
    checkpoint.
    """
    config = {"configurable": {"thread_id": run_id}}
    graph.update_state(config, decision)
    result = graph.invoke(None, config=config)
    review_queue.mark_resolved(run_id)
    return result
