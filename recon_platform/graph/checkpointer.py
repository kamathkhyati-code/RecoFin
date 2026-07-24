"""Persistent checkpointer and idempotent run entrypoint."""

from __future__ import annotations

import sqlite3
from contextlib import contextmanager

from langgraph.checkpoint.sqlite import SqliteSaver

from recon_platform.graph.build import build_graph
from recon_platform.graph.run_id import compute_run_id
from recon_platform.state import ReconState


@contextmanager
def get_checkpointer(db_path: str = "checkpoints.db"):
    """Yield a SqliteSaver backed by a local .db file.

    Because it's a file on disk, state survives process restarts, which is
    what makes a run genuinely resumable rather than just retryable within
    the same process.
    """
    conn = sqlite3.connect(db_path, check_same_thread=False)
    saver = SqliteSaver(conn)
    try:
        yield saver
    finally:
        conn.close()


def run_pipeline(
    period: str,
    source_signature: str,
    checkpointer,
    initial_state: dict | None = None,
) -> dict:
    """Run the recon graph idempotently.

    If a run with this exact run_id already completed, skip re-running
    entirely and return the cached final state instead.

    C16: if a prior attempt was interrupted mid-run (the process was
    killed, or anything else stopped it before completion), resume from
    the checkpoint with graph.invoke(None, ...) -- the LangGraph idiom
    for "continue a paused thread". Invoking with a fresh state instead
    silently restarts the whole run from START, re-executing every node
    that had already completed (double-processing ingestion, etc.) even
    though the checkpointer already has their results saved.
    """
    run_id = compute_run_id(period, source_signature)
    config = {"configurable": {"thread_id": run_id}}
    graph = build_graph(checkpointer=checkpointer)

    existing = graph.get_state(config)
    if existing.values and existing.values.get("close_ready") and not existing.next:
        return {"run_id": run_id, "skipped": True, "state": existing.values}

    if existing.values and existing.next:
        result = graph.invoke(None, config=config)
        return {"run_id": run_id, "skipped": False, "state": result}

    state: ReconState = initial_state or {
        "run_id": run_id,
        "period": period,
        "messages": [],
        "issues": [],
        "matched_count": 0,
        "unmatched_count": 0,
        "close_ready": True,
    }
    result = graph.invoke(state, config=config)
    return {"run_id": run_id, "skipped": False, "state": result}
