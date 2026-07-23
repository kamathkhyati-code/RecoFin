"""Golden matching dataset (B15).

Eight true matches spanning every matching layer, plus one genuine
book-only and one genuine source-only leftover:

- EX1/EX2  -- exact_tool:     identical amount, date, reference.
- TL1/TL2  -- tolerance_tool: amount/date drift within tolerance.
- FZ1/FZ2  -- fuzzy_tool:     reworded reference; date gap is wider than
              tolerance_tool's window so tolerance can't grab them first.
- SM1/SM2  -- semantic_match: wording too different for fuzzy_tool's
              ratio threshold; only same amount/currency ties them --
              exercises the LLM escalation path (B5) exclusively.
- UNM      -- a book txn and a source txn with no counterpart at all.
"""
from __future__ import annotations

from datetime import date
from decimal import Decimal

from datagents.schemas import Currency, SourceType, Transaction


def _txn(txn_id: str, amount: str, ref: str, day: int) -> Transaction:
    return Transaction(
        txn_id=txn_id,
        date=date(2026, 6, day),
        amount=Decimal(amount),
        currency=Currency.USD,
        counterparty="ACME",
        reference=ref,
        source=SourceType.CSV,
    )


def build_golden_dataset() -> tuple[
    list[Transaction], list[Transaction], set[tuple[str, str]], set[str], set[str]
]:
    """Return (book, source, true_pairs, true_unmatched_book_ids, true_unmatched_source_ids)."""
    book = [
        _txn("B-EX1", "100.00", "INV-100", day=1),
        _txn("B-EX2", "250.50", "INV-250", day=1),
        _txn("B-TL1", "300.00", "PAY-300", day=1),
        _txn("B-TL2", "400.00", "PAY-400", day=5),
        _txn("B-FZ1", "500.00", "Payment for invoice 500", day=1),
        _txn("B-FZ2", "600.00", "Invoice settlement 600", day=1),
        _txn("B-SM1", "700.00", "Q3 vendor payment ref XYZ123", day=1),
        _txn("B-SM2", "800.00", "REF-ALPHA-8 settlement", day=1),
        _txn("B-UNM", "999.00", "no counterpart at all", day=20),
    ]
    source = [
        _txn("S-EX1", "100.00", "INV-100", day=1),
        _txn("S-EX2", "250.50", "INV-250", day=1),
        _txn("S-TL1", "300.04", "PAY-300B", day=2),
        _txn("S-TL2", "400.03", "PAY-400B", day=6),
        _txn("S-FZ1", "500.00", "Payment for invoice #500", day=10),
        _txn("S-FZ2", "600.00", "Invoice settlement #600", day=10),
        _txn("S-SM1", "700.00", "Payment to vendor for third quarter services", day=10),
        _txn("S-SM2", "800.00", "Wire transfer received, see attached memo", day=10),
        _txn("S-UNM", "888.00", "no counterpart at all", day=20),
    ]
    true_pairs = {
        ("B-EX1", "S-EX1"),
        ("B-EX2", "S-EX2"),
        ("B-TL1", "S-TL1"),
        ("B-TL2", "S-TL2"),
        ("B-FZ1", "S-FZ1"),
        ("B-FZ2", "S-FZ2"),
        ("B-SM1", "S-SM1"),
        ("B-SM2", "S-SM2"),
    }
    return book, source, true_pairs, {"B-UNM"}, {"S-UNM"}
