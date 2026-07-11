import os
import tempfile

from recon_platform.graph.build import build_graph
from recon_platform.graph.checkpointer import get_checkpointer, run_pipeline
from recon_platform.graph.run_id import compute_run_id


def test_run_id_is_deterministic():
    id1 = compute_run_id("2026-06", "sig-abc")
    id2 = compute_run_id("2026-06", "sig-abc")
    id3 = compute_run_id("2026-06", "sig-different")
    assert id1 == id2
    assert id1 != id3


def test_interrupt_then_resume():
    with tempfile.TemporaryDirectory() as tmp:
        db_path = os.path.join(tmp, "checkpoints.db")
        with get_checkpointer(db_path) as cp:
            graph = build_graph(checkpointer=cp, interrupt_before=["matching"])
            config = {"configurable": {"thread_id": "test-thread"}}
            initial_state = {
                "run_id": "test-thread",
                "period": "2026-06",
                "messages": [],
                "issues": [],
                "matched_count": 0,
                "unmatched_count": 0,
                "close_ready": True,
            }

            graph.invoke(initial_state, config=config)
            snapshot = graph.get_state(config)
            assert "matching" in snapshot.next

            result = graph.invoke(None, config=config)
            role_values = [m.role.value for m in result["messages"]]
            assert "matching" in role_values
            assert "consolidation" in role_values


def test_completed_run_is_skipped_on_rerun():
    with tempfile.TemporaryDirectory() as tmp:
        db_path = os.path.join(tmp, "checkpoints.db")
        with get_checkpointer(db_path) as cp:
            first = run_pipeline("2026-06", "sig-xyz", cp)
            assert first["skipped"] is False

            second = run_pipeline("2026-06", "sig-xyz", cp)
            assert second["skipped"] is True
