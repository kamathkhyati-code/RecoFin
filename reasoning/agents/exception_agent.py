"""Exception Agent - B8.

Classifies each unmatched transaction, scores its risk, and suggests a
resolution. Deterministic and rule-based so classification is auditable
and testable against a labeled set, no LLM call needed for the common
cases.

Classification uses the counterpart side's leftovers as evidence: a book
txn with a same-amount source txn a few days away is a TIMING difference,
not a MISSING one; a same-date near-amount pair in different currencies is
FX; and so on.
"""

from __future__ import annotations

from decimal import Decimal

from datagents.schemas import Transaction
from reasoning.schemas import ExceptionRecord, ExcType

_TIMING_WINDOW_DAYS = 5
_MISMATCH_AMOUNT_TOL = Decimal("5.00")


def classify_exception(
    txn: Transaction, counterpart_pool: list[Transaction]
) -> ExcType:
    """Classify why txn went unmatched, given the other side's leftovers."""
    same_amount = [c for c in counterpart_pool if c.amount == txn.amount]

    for c in same_amount:
        if c.currency != txn.currency:
            return ExcType.FX

    for c in same_amount:
        if c.currency == txn.currency and abs((c.date - txn.date).days) <= _TIMING_WINDOW_DAYS:
            return ExcType.TIMING

    for c in counterpart_pool:
        if c.currency != txn.currency:
            continue
        if c.date != txn.date:
            continue
        if abs(c.amount - txn.amount) <= _MISMATCH_AMOUNT_TOL:
            return ExcType.MISMATCH

    if not counterpart_pool:
        return ExcType.MISSING

    return ExcType.UNKNOWN
