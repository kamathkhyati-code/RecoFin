"""C14: HITL end-to-end -- exception -> review -> resume -> consolidate -> close, full cycle."""

from __future__ import annotations

import os
import tempfile
from datetime import date
from decimal import Decimal

import pytest

from datagents.schemas import Currency, SourceType, Transaction
from reasoning.agents.exception_escalation import resolve_exception
from recon_platform.graph.build import build_graph, consolidation_node
from recon_platform.graph.checkpointer import get_checkpointer
from recon_platform.hitl.close_gate import PrematureCloseError, close_period
from recon_platform.hitl.resume import build_hitl_graph, resume_with_decision, start_run_with_hitl


def _txn(txn_id, amount, ref, day=1, source=SourceType.CSV):
    return Transaction(
        txn_id=txn_id,
        date=date(2026, 6, day),
        amount=Decimal(amount),
        currency=Currency.USD,
        counterparty="ACME",
        reference=ref,
        source=source,
    )


def test_full_hitl_cycle_blocks_close_until_exceptions_resolved():
    book = [_txn("B1", "999.00", "NOPE", day=20)]
    source = [_txn("S1", "555.00", "OTHER", day=25, source=SourceType.API)]

    with tempfile.TemporaryDirectory() as tmp:
        db_path = os.path.join(tmp, "checkpoints.db")
        with get_checkpointer(db_path) as cp:
            graph = build_hitl_graph(cp)
            run_id = "c14-hitl-test-1"
            initial_state = {
                "run_id": run_id,
                "period": "2026-06",
                "messages": [],
                "issues": [],
                "book_transactions": book,
                "source_transactions": source,
            }

            start_run_with_hitl(graph, run_id, initial_state)
            config = {"configurable": {"thread_id": run_id}}
            assert "resolution" in graph.get_state(config).next

            result = resume_with_decision(graph, run_id, decision={})
            report = result["report"]

            # One unmatched book txn + one unmatched source txn -> one
            # ExceptionRecord per side, both UNKNOWN (base risk 0.55) so
            # both clear the 0.5 escalation threshold.
            assert report.exception_count == 2
            assert report.close_ready is False

            with pytest.raises(PrematureCloseError):
                close_period(report)

            for exc in result["exceptions"]:
                resolve_exception(exc, run_id=run_id, analyst_note="Confirmed with bank.")

            # Re-consolidate: close_ready reflects the live, now-clear queue.
            final_state = dict(graph.get_state(config).values)
            new_report = consolidation_node(final_state)["report"]

            assert new_report.close_ready is True
            close_period(new_report)  # does not raise


def test_close_period_allows_a_run_with_no_exceptions():
    book = [_txn("B1", "100.00", "INV-001", day=1)]
    source = [_txn("S1", "100.00", "INV-001", day=1, source=SourceType.API)]
    graph = build_graph()
    result = graph.invoke(
        {
            "run_id": "c14-clean-run",
            "period": "2026-06",
            "messages": [],
            "issues": [],
            "book_transactions": book,
            "source_transactions": source,
        }
    )
    close_period(result["report"])  # does not raise
