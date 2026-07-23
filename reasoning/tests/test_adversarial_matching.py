"""Adversarial matching suite (B16).

Stresses the matcher with cases designed to trick it: near-duplicate
amounts on unrelated transactions, currency edges, and reference
collisions. The bar isn't "never proposes a coincidental candidate" --
deterministic tools work on incomplete signals -- it's "never lets a
coincidental match through as an unreviewed auto-match."
"""
from __future__ import annotations

from datetime import date
from decimal import Decimal

from datagents.schemas import Currency, SourceType, Transaction
from reasoning.schemas import MatchResult, MatchType
from reasoning.thresholds import AUTO_MATCH_THRESHOLD, split_auto_and_review
from reasoning.tools.matching_tools import exact_tool, fuzzy_tool, tolerance_tool


def _txn(txn_id, amount, ref, day, currency=Currency.USD):
    return Transaction(
        txn_id=txn_id,
        date=date(2026, 6, day),
        amount=Decimal(amount),
        currency=currency,
        counterparty="ACME",
        reference=ref,
        source=SourceType.CSV,
    )


def test_currency_edge_never_matches_across_tools():
    book = [_txn("B1", "100.00", "INV-1", day=1, currency=Currency.USD)]
    source = [_txn("S1", "100.00", "INV-1", day=1, currency=Currency.EUR)]
    assert exact_tool(book, source) == []
    assert tolerance_tool(book, source) == []
    assert fuzzy_tool(book, source) == []


def test_near_duplicate_amount_unrelated_transactions_not_auto_matched():
    # Two genuinely unrelated payments that happen to land within
    # tolerance_tool's amount/date window. tolerance_tool has no view of
    # reference text, so it may still propose this pair -- the system's
    # job is to keep its confidence below the auto-match floor.
    book = [_txn("B1", "1000.00", "Payroll batch 44", day=10)]
    source = [_txn("S1", "1000.04", "Vendor refund 91", day=11)]
    matches = tolerance_tool(book, source)
    assert len(matches) == 1
    auto, review = split_auto_and_review(matches)
    assert auto == []
    assert len(review) == 1


def test_near_duplicate_reference_does_not_cross_match_wrong_pair():
    # Two legitimate pairs with confusingly similar invoice numbers.
    # The greedy assignment must still pick the correct (best-scoring)
    # pairing, not an adversarial cross-match.
    book = [
        _txn("B1", "500.00", "INV-1001", day=1),
        _txn("B2", "700.00", "INV-1002", day=1),
    ]
    source = [
        _txn("S1", "500.00", "INV-1001", day=1),
        _txn("S2", "700.00", "INV-1002", day=1),
    ]
    matches = exact_tool(book, source)
    pairs = {(m.book_txn_id, m.source_txn_id) for m in matches}
    assert pairs == {("B1", "S1"), ("B2", "S2")}


def test_auto_match_floor_rejects_low_confidence_fuzzy():
    book = [_txn("B1", "500.00", "Payment ref alpha delivery", day=1)]
    source = [_txn("S1", "500.00", "Payment note delivery alpha", day=1)]
    matches = fuzzy_tool(book, source, min_ratio=0.3)
    if matches:
        auto, review = split_auto_and_review(matches)
        assert auto == []


def test_threshold_helpers_split_correctly():
    high = MatchResult(
        book_txn_id="B1",
        source_txn_id="S1",
        match_type=MatchType.EXACT,
        confidence=1.0,
        rule="exact",
    )
    low = MatchResult(
        book_txn_id="B2",
        source_txn_id="S2",
        match_type=MatchType.TOLERANCE,
        confidence=0.65,
        rule="tolerance",
    )
    auto, review = split_auto_and_review([high, low], threshold=AUTO_MATCH_THRESHOLD)
    assert auto == [high]
    assert review == [low]
