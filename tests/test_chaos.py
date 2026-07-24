"""C16: reliability + chaos -- idempotency across retries, dedupe on
resumed runs, kill-mid-run tests.

Found and fixed a real bug while building this: run_pipeline (C4) checked
whether an interrupted run should resume, but then invoked with a fresh
state instead of None, which silently restarts the whole graph from
START and double-processes every already-completed node (see the fix in
recon_platform/graph/checkpointer.py). These tests pin that fix down as
a permanent regression test, and extend it to real golden data and a
multi-restart scenario.
"""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

from datagents.schemas import SourceConfig, SourceType
from recon_platform.graph.build import build_graph
from recon_platform.graph.checkpointer import get_checkpointer, run_pipeline
from recon_platform.graph.run_id import compute_run_id

_SAMPLE_DIR = Path(__file__).resolve().parent.parent / "sample_data"
_FIELD_MAP = {"transaction_id": "txn_id", "value_date": "date", "ccy": "currency"}


def _synthetic_state(run_id: str, period: str) -> dict:
    return {
        "run_id": run_id,
        "period": period,
        "messages": [],
        "issues": [],
        "matched_count": 0,
        "unmatched_count": 0,
        "close_ready": True,
    }


def _golden_state(run_id: str, period: str) -> dict:
    return {
        "run_id": run_id,
        "period": period,
        "messages": [],
        "issues": [],
        "book_source_configs": [
            SourceConfig(name="book", source_type=SourceType.CSV, location=str(_SAMPLE_DIR / "book.csv")),
        ],
        "bank_source_configs": [
            SourceConfig(
                name="bank",
                source_type=SourceType.CSV,
                location=str(_SAMPLE_DIR / "bank_source.csv"),
                options={"field_map": _FIELD_MAP},
            ),
        ],
    }


def test_kill_after_ingestion_resume_via_run_pipeline_no_double_processing():
    """Regression test for the run_pipeline resume bug found while
    building this suite."""
    period, sig = "2026-06", "chaos-sig-1"
    run_id = compute_run_id(period, sig)

    with tempfile.TemporaryDirectory() as tmp:
        db_path = os.path.join(tmp, "checkpoints.db")
        with get_checkpointer(db_path) as cp:
            graph = build_graph(checkpointer=cp, interrupt_before=["matching"])
            config = {"configurable": {"thread_id": run_id}}
            graph.invoke(_synthetic_state(run_id, period), config=config)
            assert "matching" in graph.get_state(config).next  # confirms it's genuinely paused

            result = run_pipeline(period, sig, cp)

            role_values = [m.role.value for m in result["state"]["messages"]]
            assert role_values.count("ingestion") == 1
            assert role_values.count("validation") == 1
            assert role_values.count("normalization") == 1
            assert "matching" in role_values
            assert "consolidation" in role_values


def test_kill_mid_real_ingestion_resume_produces_exact_row_counts():
    """Same scenario with real golden-data ingestion: kill right after
    ingestion/validation/normalization complete, resume, and confirm the
    transaction count is exact -- not duplicated."""
    period, sig = "2026-01", "chaos-golden-1"
    run_id = compute_run_id(period, sig)

    with tempfile.TemporaryDirectory() as tmp:
        db_path = os.path.join(tmp, "checkpoints.db")
        with get_checkpointer(db_path) as cp:
            graph = build_graph(checkpointer=cp, interrupt_before=["matching"])
            config = {"configurable": {"thread_id": run_id}}
            graph.invoke(_golden_state(run_id, period), config=config)
            assert "matching" in graph.get_state(config).next

            result = run_pipeline(period, sig, cp)
            state = result["state"]

            # book.csv (4 rows) + bank_source.csv (3 clean rows, 2 rejected
            # at ingestion) -- exact, not doubled by the kill+resume cycle.
            assert len(state["transactions"]) == 7
            assert len(state["book_transactions"]) == 4
            assert len(state["source_transactions"]) == 3
            report = state["report"]
            assert report.matched_count == 3
            assert report.unmatched_count == 1


def test_completed_run_via_run_pipeline_is_still_skipped():
    """The fix must not break C4's original skip-if-complete guarantee."""
    with tempfile.TemporaryDirectory() as tmp:
        db_path = os.path.join(tmp, "checkpoints.db")
        with get_checkpointer(db_path) as cp:
            first = run_pipeline("2026-06", "chaos-sig-2", cp)
            assert first["skipped"] is False

            second = run_pipeline("2026-06", "chaos-sig-2", cp)
            assert second["skipped"] is True
            assert second["state"] == first["state"]


def test_multiple_restarts_at_different_points_do_not_accumulate_duplicates():
    """A more realistic chaos scenario: the process is killed and
    restarted twice, pausing at a *different* point each time (as a real
    redeploy landing mid-retry-loop might). Each restart must pick up
    exactly where the last one left off, never re-run a completed node."""
    period, sig = "2026-06", "chaos-multi-restart"
    run_id = compute_run_id(period, sig)

    with tempfile.TemporaryDirectory() as tmp:
        db_path = os.path.join(tmp, "checkpoints.db")
        with get_checkpointer(db_path) as cp:
            config = {"configurable": {"thread_id": run_id}}

            # Attempt 1: killed right after ingestion.
            graph_a = build_graph(checkpointer=cp, interrupt_before=["validation"])
            graph_a.invoke(_synthetic_state(run_id, period), config=config)
            assert "validation" in graph_a.get_state(config).next

            # Attempt 2 (different process/deploy): resumes, killed before matching.
            graph_b = build_graph(checkpointer=cp, interrupt_before=["matching"])
            graph_b.invoke(None, config=config)
            assert "matching" in graph_b.get_state(config).next

            # Attempt 3: resumes to completion, no interrupt this time.
            graph_c = build_graph(checkpointer=cp)
            result = graph_c.invoke(None, config=config)

            role_values = [m.role.value for m in result["messages"]]
            assert role_values.count("ingestion") == 1
            assert role_values.count("validation") == 1
            assert role_values.count("normalization") == 1
            assert role_values.count("matching") == 1
            assert role_values.count("consolidation") == 1
