"""Tests for the deterministic matching agent (B4)."""
from __future__ import annotations

from datetime import date
from decimal import Decimal

from datagents.schemas import Currency, SourceType, Transaction
from recon_platform.state import MessageRole
from reasoning.agents.matching_agent import matching_agent, run_matching


def _txn(txn_id, amount, ref, day=1):
    return Transaction(
        txn_id=txn_id,
        date=date(2026, 6, day),
        amount=Decimal(amount),
        currency=Currency.USD,
        counterparty="ACME",
        reference=ref,
        source=SourceType.CSV,
    )


def _fixture():
    book = [
        _txn("B1", "100.00", "INV-001", day=1),
        _txn("B2", "200.00", "PAY-2", day=5),
        _txn("B3", "300.00", "Payment for invoice 300", day=10),
        _txn("B4", "999.00", "NOPE", day=20),
    ]
    source = [
        _txn("S1", "100.00", "INV-001", day=1),
        _txn("S2", "200.03", "PAY-2X", day=6),
        _txn("S3", "300.00", "Payment for invoice #300", day=25),
        _txn("S4", "555.00", "OTHER", day=25),
    ]
    return book, source


def test_run_matching_matches_and_leftovers():
    book, source = _fixture()
    matches, ub, us = run_matching(book, source)
    assert len(matches) == 3
    assert {m.book_txn_id for m in matches} == {"B1", "B2", "B3"}
    assert [t.txn_id for t in ub] == ["B4"]
    assert [t.txn_id for t in us] == ["S4"]


def test_all_three_strategies_contribute():
    book, source = _fixture()
    matches, _, _ = run_matching(book, source)
    rules = {m.book_txn_id: m.rule for m in matches}
    assert rules["B1"] == "exact"
    assert rules["B2"] == "tolerance"
    assert rules["B3"] == "fuzzy"


def test_no_transaction_matched_twice():
    book, source = _fixture()
    matches, _, _ = run_matching(book, source)
    book_ids = [m.book_txn_id for m in matches]
    source_ids = [m.source_txn_id for m in matches]
    assert len(book_ids) == len(set(book_ids))
    assert len(source_ids) == len(set(source_ids))


def test_strongest_first_exact_beats_tolerance():
    book = [_txn("B1", "100.00", "INV-001", day=1)]
    source = [
        _txn("S1", "100.00", "INV-001", day=1),
        _txn("S1b", "100.02", "INV-001", day=2),
    ]
    matches, _, us = run_matching(book, source)
    assert len(matches) == 1
    assert matches[0].source_txn_id == "S1"
    assert matches[0].rule == "exact"
    assert [t.txn_id for t in us] == ["S1b"]


def test_matching_agent_node_writes_state():
    book, source = _fixture()
    state = {"book_transactions": book, "source_transactions": source}
    out = matching_agent(state)
    assert out["matched_count"] == 3
    assert out["unmatched_count"] == 2
    assert len(out["match_results"]) == 3
    assert [t.txn_id for t in out["unmatched_book"]] == ["B4"]
    assert [t.txn_id for t in out["unmatched_source"]] == ["S4"]
    assert out["messages"][0].role is MessageRole.MATCHING


def test_matching_agent_handles_empty_state():
    out = matching_agent({})
    assert out["matched_count"] == 0
    assert out["unmatched_count"] == 0
    assert out["match_results"] == []
