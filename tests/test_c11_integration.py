"""C11 (partial): E2E golden-data traversal through the real (B-side) graph.

Proves matching_node, resolution_node, and consolidation_node (B11 + the
consolidation change alongside this file) genuinely compose into a
working ReconReport when given real transactions.

This is NOT full C11. C11's spec is "assemble A+B agents into the real
graph" -- A11 (Intern A's data-agent integration) does not exist yet, so
ingestion/validation/normalization remain placeholders. This test
supplies book_transactions/source_transactions directly in initial_state,
standing in for what A11's real ingestion/validation/normalization
pipeline will eventually produce from source_configs. Once A11 lands,
extend this test (or add a sibling) to derive them from real
source_configs via the real A-agents instead of injecting them directly.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from datagents.schemas import Currency, SourceType, Transaction
from recon_platform.graph.build import build_graph
from recon_platform.state import ReconState


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


def test_e2e_golden_data_with_exceptions_through_real_graph():
    book = [
        _txn("B1", "100.00", "INV-001", day=1),
        _txn("B2", "200.00", "PAY-2", day=5),
        _txn("B3", "999.00", "NOPE", day=20),
    ]
    source = [
        _txn("S1", "100.00", "INV-001", day=1, source=SourceType.API),
        _txn("S2", "200.03", "PAY-2X", day=6, source=SourceType.API),
        _txn("S4", "555.00", "OTHER", day=25, source=SourceType.API),
    ]
    graph = build_graph()
    initial_state: ReconState = {
        "run_id": "c11-golden-1",
        "period": "2026-06",
        "messages": [],
        "issues": [],
        "book_transactions": book,
        "source_transactions": source,
    }

    result = graph.invoke(initial_state)
    report = result["report"]

    assert report.run_id == "c11-golden-1"
    assert report.matched_count == 2
    assert report.unmatched_count == 2
    assert report.exception_count == 2
    assert 0.0 < report.match_rate < 1.0
    assert report.close_ready is False

    role_values = [m.role.value for m in result["messages"]]
    assert "matching" in role_values
    assert "resolution" in role_values
    assert "consolidation" in role_values
    assert "learning" not in role_values


def test_e2e_fully_matched_golden_data_is_close_ready():
    book = [_txn("B1", "100.00", "INV-001", day=1)]
    source = [_txn("S1", "100.00", "INV-001", day=1, source=SourceType.API)]
    graph = build_graph()
    initial_state: ReconState = {
        "run_id": "c11-golden-2",
        "period": "2026-06",
        "messages": [],
        "issues": [],
        "book_transactions": book,
        "source_transactions": source,
    }

    result = graph.invoke(initial_state)
    report = result["report"]

    assert report.matched_count == 1
    assert report.unmatched_count == 0
    assert report.exception_count == 0
    assert report.match_rate == 1.0
    assert report.close_ready is True

    role_values = [m.role.value for m in result["messages"]]
    assert "learning" in role_values
