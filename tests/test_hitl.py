import os
import tempfile

from recon_platform.graph.checkpointer import get_checkpointer
from recon_platform.hitl.resume import build_hitl_graph, start_run_with_hitl, resume_with_decision
from recon_platform.hitl.review_queue import review_queue


def test_graph_pauses_at_resolution_when_unmatched():
    with tempfile.TemporaryDirectory() as tmp:
        db_path = os.path.join(tmp, "checkpoints.db")
        with get_checkpointer(db_path) as cp:
            graph = build_hitl_graph(cp)
            run_id = "hitl-test-1"
            initial_state = {
                "run_id": run_id,
                "period": "2026-06",
                "messages": [],
                "issues": [],
                "matched_count": 0,
                "unmatched_count": 3,
                "close_ready": True,
            }

            start_run_with_hitl(graph, run_id, initial_state)

            snapshot = graph.get_state({"configurable": {"thread_id": run_id}})
            assert "resolution" in snapshot.next

            item = review_queue.get(run_id)
            assert item is not None
            assert item.resolved is False


def test_resume_with_decision_completes_run():
    with tempfile.TemporaryDirectory() as tmp:
        db_path = os.path.join(tmp, "checkpoints.db")
        with get_checkpointer(db_path) as cp:
            graph = build_hitl_graph(cp)
            run_id = "hitl-test-2"
            initial_state = {
                "run_id": run_id,
                "period": "2026-06",
                "messages": [],
                "issues": [],
                "matched_count": 0,
                "unmatched_count": 2,
                "close_ready": True,
            }

            start_run_with_hitl(graph, run_id, initial_state)

            result = resume_with_decision(graph, run_id, decision={"unmatched_count": 0})

            role_values = [m.role.value for m in result["messages"]]
            assert "consolidation" in role_values
            assert "learning" in role_values

            item = review_queue.get(run_id)
            assert item.resolved is True
