"""A14: validation escalation to HITL -- ambiguous row -> review queue ->
resume after mock approval, full cycle.

An ambiguous row (no reference) that the LLM flags "review" (via
MockLLMGateway, since no real LLM is configured in this project) should:
  1. get tagged severity="review" by validation_node (not "warning"/"error")
  2. route straight to "resolution" via validation_gate (A14's addition to
     routing.py), independent of the existing critical-issue retry loop
  3. register on the review queue and pause there (reusing B9/C14's
     existing interrupt_before=["resolution"] machinery unchanged)
  4. resume and complete once a mock analyst decision comes in, via the
     same start_run_with_hitl/resume_with_decision API C14's exception
     flow already uses

The gateway is injected via monkeypatching build.py's module-level
_LLM_GATEWAY, not via state: a live gateway object isn't
checkpointer-serializable, and HITL runs persist state to SQLite between
pause and resume (confirmed by an actual msgpack TypeError on a first
attempt that threaded the gateway through state instead).
"""

from __future__ import annotations

import os
import tempfile
from datetime import date
from decimal import Decimal

from datagents.schemas import Currency, SourceType, Transaction
from recon_platform.gateway.llm_gateway import MockLLMGateway
from recon_platform.graph.checkpointer import get_checkpointer
from recon_platform.hitl.resume import build_hitl_graph, resume_with_decision, start_run_with_hitl
from recon_platform.hitl.review_queue import review_queue


def _ambiguous_txn(txn_id="A1"):
    return Transaction(
        txn_id=txn_id,
        date=date(2026, 6, 1),
        amount=Decimal("100.00"),
        currency=Currency.USD,
        counterparty="ACME",
        reference=None,  # no reference -> ambiguous, eligible for LLM judgment
        source=SourceType.CSV,
    )


def test_ambiguous_row_escalates_to_resolution_and_registers_on_review_queue(monkeypatch):
    monkeypatch.setattr(
        "recon_platform.graph.build._LLM_GATEWAY",
        MockLLMGateway('{"verdict": "review", "confidence": 0.3, "reason": "no reference to anchor it"}'),
    )

    with tempfile.TemporaryDirectory() as tmp:
        db_path = os.path.join(tmp, "checkpoints.db")
        with get_checkpointer(db_path) as cp:
            graph = build_hitl_graph(cp)
            run_id = "a14-validation-hitl-1"
            initial_state = {
                "run_id": run_id,
                "period": "2026-06",
                "messages": [],
                "issues": [],
                "transactions": [_ambiguous_txn()],
            }

            start_run_with_hitl(graph, run_id, initial_state)

            snapshot = graph.get_state({"configurable": {"thread_id": run_id}})
            assert "resolution" in snapshot.next

            item = review_queue.get(run_id)
            assert item is not None
            assert item.resolved is False


def test_ambiguous_row_resumes_and_completes_after_mock_approval(monkeypatch):
    monkeypatch.setattr(
        "recon_platform.graph.build._LLM_GATEWAY",
        MockLLMGateway('{"verdict": "review", "confidence": 0.3, "reason": "no reference to anchor it"}'),
    )

    with tempfile.TemporaryDirectory() as tmp:
        db_path = os.path.join(tmp, "checkpoints.db")
        with get_checkpointer(db_path) as cp:
            graph = build_hitl_graph(cp)
            run_id = "a14-validation-hitl-2"
            initial_state = {
                "run_id": run_id,
                "period": "2026-06",
                "messages": [],
                "issues": [],
                "transactions": [_ambiguous_txn()],
            }

            start_run_with_hitl(graph, run_id, initial_state)

            # Mock analyst approval: no state change needed to unblock this
            # row (it's not an unmatched-count style decision), just resume.
            result = resume_with_decision(graph, run_id, decision={})

            role_values = [m.role.value for m in result["messages"]]
            assert "resolution" in role_values
            assert "consolidation" in role_values

            item = review_queue.get(run_id)
            assert item.resolved is True


def test_clean_row_with_reference_does_not_escalate(monkeypatch):
    """Control case: a row WITH a reference is never ambiguous in the first
    place (validate_transactions only judges reference-less rows), so it
    must sail straight through to normalization/matching, never pausing --
    even with a gateway configured that would say "review" if it were ever
    called (proving it genuinely never gets called for this row).
    """
    from recon_platform.graph.build import build_graph

    monkeypatch.setattr(
        "recon_platform.graph.build._LLM_GATEWAY",
        MockLLMGateway('{"verdict": "review", "confidence": 0.1, "reason": "should never be called"}'),
    )

    txn = Transaction(
        txn_id="A2",
        date=date(2026, 6, 1),
        amount=Decimal("50.00"),
        currency=Currency.USD,
        counterparty="ACME",
        reference="INV-1",
        source=SourceType.CSV,
    )

    graph = build_graph()
    result = graph.invoke({
        "run_id": "a14-clean-row",
        "period": "2026-06",
        "messages": [],
        "issues": [],
        "transactions": [txn],
    })

    role_values = [m.role.value for m in result["messages"]]
    assert "resolution" not in role_values
    assert "normalization" in role_values
