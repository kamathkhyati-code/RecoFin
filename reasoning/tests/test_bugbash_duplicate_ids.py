"""Regression test for the B19 bug bash finding: duplicate txn_ids used
to cause a legitimate match to be silently dropped by the greedy
assigner, with no error raised. Each matching tool must now fail loudly
instead.
"""
from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from datagents.schemas import Currency, SourceType, Transaction
from reasoning.tools.matching_tools import exact_tool, fuzzy_tool, tolerance_tool


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


def test_exact_tool_rejects_duplicate_book_txn_id():
    book = [_txn("B1", "100.00", "INV-1"), _txn("B1", "200.00", "INV-2")]
    source = [_txn("S1", "100.00", "INV-1"), _txn("S2", "200.00", "INV-2")]
    with pytest.raises(ValueError, match="duplicate txn_id"):
        exact_tool(book, source)


def test_exact_tool_rejects_duplicate_source_txn_id():
    book = [_txn("B1", "100.00", "INV-1"), _txn("B2", "200.00", "INV-2")]
    source = [_txn("S1", "100.00", "INV-1"), _txn("S1", "200.00", "INV-2")]
    with pytest.raises(ValueError, match="duplicate txn_id"):
        exact_tool(book, source)


def test_tolerance_tool_rejects_duplicate_txn_id():
    book = [_txn("B1", "100.00", "x"), _txn("B1", "100.02", "y")]
    source = [_txn("S1", "100.00", "x")]
    with pytest.raises(ValueError, match="duplicate txn_id"):
        tolerance_tool(book, source)


def test_fuzzy_tool_rejects_duplicate_txn_id():
    book = [
        _txn("B1", "500.00", "Payment for invoice 500"),
        _txn("B1", "500.00", "Some other wording"),
    ]
    source = [_txn("S1", "500.00", "Payment for invoice #500")]
    with pytest.raises(ValueError, match="duplicate txn_id"):
        fuzzy_tool(book, source)


def test_unique_ids_still_work_normally():
    # Sanity check: the guard only rejects genuine duplicates, not
    # ordinary distinct transactions.
    book = [_txn("B1", "100.00", "INV-1"), _txn("B2", "200.00", "INV-2")]
    source = [_txn("S1", "100.00", "INV-1"), _txn("S2", "200.00", "INV-2")]
    matches = exact_tool(book, source)
    assert len(matches) == 2
