"""Per-strategy unit tests for the deterministic matching tools."""
from __future__ import annotations

from datetime import date
from decimal import Decimal

from datagents.schemas import Currency, SourceType, Transaction
from recon_platform.registry import registry
from reasoning.schemas import MatchType
from reasoning.tools.matching_tools import exact_tool, fuzzy_tool, tolerance_tool


def _txn(txn_id, amount, ref, day=1, currency=Currency.USD):
    return Transaction(
        txn_id=txn_id,
        date=date(2026, 6, day),
        amount=Decimal(amount),
        currency=currency,
        counterparty="ACME",
        reference=ref,
        source=SourceType.CSV,
    )


def test_tools_registered_in_registry():
    names = registry.list_tools()
    for n in ("exact_tool", "tolerance_tool", "fuzzy_tool"):
        assert n in names
        assert callable(registry.get(n).func)


def test_registry_resolves_same_function():
    assert registry.get("exact_tool").func is exact_tool


def test_exact_tool_matches_identical():
    book = [_txn("B1", "100.00", "INV-001", day=1)]
    source = [_txn("S1", "100.00", "INV-001", day=1)]
    matches = exact_tool(book, source)
    assert len(matches) == 1
    m = matches[0]
    assert m.book_txn_id == "B1" and m.source_txn_id == "S1"
    assert m.match_type is MatchType.EXACT
    assert m.confidence == 1.0
    assert m.rule and m.rationale


def test_exact_tool_rejects_near_miss():
    book = [_txn("B1", "100.00", "INV-001", day=1)]
    source = [_txn("S1", "100.03", "INV-001", day=1)]
    assert exact_tool(book, source) == []


def test_tolerance_tool_matches_within_window():
    book = [_txn("B2", "200.00", "PAY-2", day=5)]
    source = [_txn("S2", "200.03", "PAY-2X", day=6)]
    matches = tolerance_tool(book, source)
    assert len(matches) == 1
    m = matches[0]
    assert m.match_type is MatchType.TOLERANCE
    assert 0.0 < m.confidence < 1.0
    assert m.rule and m.rationale


def test_tolerance_tool_rejects_outside_window():
    book = [_txn("B2", "200.00", "PAY-2", day=5)]
    source = [_txn("S2", "250.00", "PAY-2", day=5)]
    assert tolerance_tool(book, source) == []


def test_fuzzy_tool_matches_reworded_reference():
    book = [_txn("B3", "300.00", "Payment for invoice 300", day=10)]
    source = [_txn("S3", "300.00", "Payment for invoice #300", day=10)]
    matches = fuzzy_tool(book, source)
    assert len(matches) == 1
    m = matches[0]
    assert m.match_type is MatchType.FUZZY
    assert 0.0 < m.confidence < 1.0
    assert m.rule and m.rationale


def test_fuzzy_tool_rejects_dissimilar_reference():
    book = [_txn("B3", "300.00", "totally unrelated text", day=10)]
    source = [_txn("S3", "300.00", "xyz", day=10)]
    assert fuzzy_tool(book, source) == []


def test_greedy_one_to_one_no_double_match():
    book = [
        _txn("B1", "100.00", "INV-001", day=1),
        _txn("B1b", "100.00", "INV-001", day=1),
    ]
    source = [_txn("S1", "100.00", "INV-001", day=1)]
    matches = exact_tool(book, source)
    assert len(matches) == 1
    assert matches[0].source_txn_id == "S1"
