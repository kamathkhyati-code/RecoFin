"""Tests for B10: matching sub-graph (matching -> exception classification)."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from datagents.schemas import Currency, SourceType, Transaction
from reasoning.match_subgraph import run_match_subgraph
from reasoning.memory.match_memory import MatchMemory
from reasoning.rule_store import RuleStore
from reasoning.schemas import MatchResult, MatchType, RuleSuggestion


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


def _golden_fixture():
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


def test_match_subgraph_matches_and_classifies_on_golden_data():
    book, source = _golden_fixture()
    state = {"book_transactions": book, "source_transactions": source}

    result = run_match_subgraph(state)

    assert len(result["match_results"]) == 3
    assert {m.book_txn_id for m in result["match_results"]} == {"B1", "B2", "B3"}
    assert [t.txn_id for t in result["unmatched_book"]] == ["B4"]
    assert [t.txn_id for t in result["unmatched_source"]] == ["S4"]

    assert len(result["exceptions"]) == 2
    sides = {e.side for e in result["exceptions"]}
    assert sides == {"book", "source"}
    for exc in result["exceptions"]:
        assert 0.0 <= exc.risk_score <= 1.0
        assert exc.suggested_resolution


def test_match_subgraph_state_keys_present():
    book, source = _golden_fixture()
    state = {"book_transactions": book, "source_transactions": source}
    result = run_match_subgraph(state)
    assert "match_results" in result
    assert "unmatched_book" in result
    assert "unmatched_source" in result
    assert "exceptions" in result


def test_match_subgraph_handles_empty_state():
    result = run_match_subgraph({})
    assert result["match_results"] == []
    assert result["unmatched_book"] == []
    assert result["unmatched_source"] == []
    assert result["exceptions"] == []


def test_match_subgraph_with_memory_boosts_confidence_on_known_pair():
    book, source = _golden_fixture()
    memory = MatchMemory()

    # Pre-seed memory with the exact B2/S2 pair as a previously confirmed match.
    seed = MatchResult(
        book_txn_id="B2", source_txn_id="S2", match_type=MatchType.TOLERANCE,
        confidence=0.67, rule="tolerance",
    )
    memory.upsert_match(next(t for t in book if t.txn_id == "B2"), next(t for t in source if t.txn_id == "S2"), seed)

    state = {"book_transactions": book, "source_transactions": source}
    result_without_memory = run_match_subgraph(state)
    result_with_memory = run_match_subgraph(state, memory=memory)

    raw = next(m.confidence for m in result_without_memory["match_results"] if m.book_txn_id == "B2")
    calibrated = next(m.confidence for m in result_with_memory["match_results"] if m.book_txn_id == "B2")
    assert calibrated > raw


def test_c12_approved_widen_tolerance_applies_on_next_run():
    """The closed learning loop (C12): approve a rule, next run reflects it."""
    book = [_txn("B1", "100.00", "INV-1", day=1)]
    source = [_txn("S1", "100.07", "INV-1", day=1)]  # delta 0.07 > default amount_tol 0.05
    store = RuleStore()
    state = {"book_transactions": book, "source_transactions": source}

    result_before = run_match_subgraph(dict(state), rule_store=store)
    assert not any(m.rule == "tolerance" for m in result_before["match_results"])

    item = store.add(
        RuleSuggestion(
            rule_type="widen_tolerance",
            description="widen to cover observed delta",
            suggested_params={"amount_tol": "0.10"},
        )
    )
    store.approve(item.item_id)

    result_after = run_match_subgraph(dict(state), rule_store=store)
    tolerance_matches = [m for m in result_after["match_results"] if m.rule == "tolerance"]
    assert len(tolerance_matches) == 1
    assert tolerance_matches[0].book_txn_id == "B1"
