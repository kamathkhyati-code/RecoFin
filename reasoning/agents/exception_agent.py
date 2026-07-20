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

# Base risk by exception type: TIMING tends to self-resolve, MISSING/UNKNOWN
# have no counterpart evidence at all so they carry the most risk.
_BASE_RISK = {
    ExcType.TIMING: 0.2,
    ExcType.FX: 0.35,
    ExcType.MISMATCH: 0.5,
    ExcType.UNKNOWN: 0.55,
    ExcType.MISSING: 0.6,
}
_MATERIALITY_DIVISOR = Decimal("100000")
_MAX_MATERIALITY_BUMP = 0.4

_RESOLUTIONS = {
    ExcType.MISSING: "Confirm the counterpart transaction was received; investigate a settlement delay or a missing feed.",
    ExcType.MISMATCH: "Verify the amount discrepancy with the counterparty; check for fees or a partial settlement.",
    ExcType.FX: "Confirm the FX rate applied and reconcile using the agreed conversion rate.",
    ExcType.TIMING: "Wait for the counterpart to settle within the expected timing window, then re-run reconciliation.",
    ExcType.UNKNOWN: "No clear counterpart pattern found; escalate for manual review.",
}


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


def score_risk(txn: Transaction, exc_type: ExcType) -> float:
    """Blend the exception type's base risk with a materiality bump.

    Larger transactions carry more risk regardless of exception type, but
    the bump saturates so score_risk never exceeds 1.0.
    """
    base = _BASE_RISK.get(exc_type, 0.5)
    materiality_bump = min(float(txn.amount / _MATERIALITY_DIVISOR), _MAX_MATERIALITY_BUMP)
    return max(0.0, min(1.0, base + materiality_bump))


def suggest_resolution(exc_type: ExcType) -> str:
    """A human-readable next step for an analyst working this exception type."""
    return _RESOLUTIONS.get(exc_type, "Escalate for manual review.")


def exception_agent(book: list[Transaction], source: list[Transaction]) -> list[ExceptionRecord]:
    """Classify, risk-score, and suggest a resolution for every unmatched txn on both sides."""
    records: list[ExceptionRecord] = []

    for txn in book:
        exc_type = classify_exception(txn, source)
        records.append(
            ExceptionRecord(
                txn_id=txn.txn_id,
                side="book",
                exc_type=exc_type,
                risk_score=score_risk(txn, exc_type),
                suggested_resolution=suggest_resolution(exc_type),
                rationale=f"Classified as {exc_type.value} against {len(source)} source counterpart(s).",
            )
        )

    for txn in source:
        exc_type = classify_exception(txn, book)
        records.append(
            ExceptionRecord(
                txn_id=txn.txn_id,
                side="source",
                exc_type=exc_type,
                risk_score=score_risk(txn, exc_type),
                suggested_resolution=suggest_resolution(exc_type),
                rationale=f"Classified as {exc_type.value} against {len(book)} book counterpart(s).",
            )
        )

    return records
