"""Deterministic matching tools: exact, tolerance, fuzzy.
Each tool compares book vs source transactions and returns one-to-one
MatchResults (greedy, best-first within the tool). Every result carries a
confidence, a rule name, and a human-readable rationale. All three tools are
registered in the shared ToolRegistry so the matching agent can resolve them
by name (Architecture tab: run strategy tools strongest-first).

Confidence scale (demo-integration override, not the intern-b original):
  exact match (amount+date+reference)      -> 1.0
  tolerance match (amount+date, no ref)    -> 0.80 flat
  fuzzy match (amount+reference similarity) -> 0.65 flat
"""
from __future__ import annotations
import difflib
from decimal import Decimal
from datagents.schemas import Transaction
from recon_platform.registry import registry
from reasoning.schemas import MatchResult, MatchType
def _norm_ref(ref: str | None) -> str:
    """Lowercase, strip, and collapse whitespace in a reference string."""
    if not ref:
        return ""
    return " ".join(ref.strip().lower().split())
def _greedy(candidates: list[tuple[float, MatchResult]]) -> list[MatchResult]:
    """Assign candidates best-first, one book and one source txn each."""
    used_book: set[str] = set()
    used_source: set[str] = set()
    out: list[MatchResult] = []
    for _, mr in sorted(candidates, key=lambda c: c[0], reverse=True):
        if mr.book_txn_id in used_book or mr.source_txn_id in used_source:
            continue
        used_book.add(mr.book_txn_id)
        used_source.add(mr.source_txn_id)
        out.append(mr)
    return out
@registry.register(
    "exact_tool",
    description="Match on identical currency, amount, date, and reference.",
)
def exact_tool(
    book: list[Transaction], source: list[Transaction]
) -> list[MatchResult]:
    """Match on identical currency, amount, date, and reference."""
    candidates: list[tuple[float, MatchResult]] = []
    for b in book:
        for s in source:
            if b.currency != s.currency or b.amount != s.amount or b.date != s.date:
                continue
            bref = _norm_ref(b.reference)
            if not bref or bref != _norm_ref(s.reference):
                continue
            mr = MatchResult(
                book_txn_id=b.txn_id,
                source_txn_id=s.txn_id,
                match_type=MatchType.EXACT,
                confidence=1.0,
                rule="exact",
                rationale=(
                    f"identical amount {b.amount} {b.currency.value}, "
                    f"date {b.date}, reference '{b.reference}'"
                ),
            )
            candidates.append((1.0, mr))
    return _greedy(candidates)
@registry.register(
    "tolerance_tool",
    description="Match within an amount tolerance and a +/- date window.",
)
def tolerance_tool(
    book: list[Transaction],
    source: list[Transaction],
    *,
    amount_tol: Decimal = Decimal("0.05"),
    date_window: int = 2,
) -> list[MatchResult]:
    """Match within an amount tolerance and a +/- date window."""
    candidates: list[tuple[float, MatchResult]] = []
    for b in book:
        for s in source:
            if b.currency != s.currency:
                continue
            amt_delta = abs(b.amount - s.amount)
            if amt_delta > amount_tol:
                continue
            day_delta = abs((b.date - s.date).days)
            if day_delta > date_window:
                continue
            confidence = 0.80
            mr = MatchResult(
                book_txn_id=b.txn_id,
                source_txn_id=s.txn_id,
                match_type=MatchType.TOLERANCE,
                confidence=confidence,
                rule="tolerance",
                rationale=(
                    f"amount within {amount_tol} (delta {amt_delta}), "
                    f"date within {date_window}d (delta {day_delta}d)"
                ),
                metadata={
                    "amount_delta": str(amt_delta),
                    "date_delta_days": day_delta,
                },
            )
            candidates.append((confidence, mr))
    return _greedy(candidates)
@registry.register(
    "fuzzy_tool",
    description="Match on fuzzy reference similarity with a close-amount guard.",
)
def fuzzy_tool(
    book: list[Transaction],
    source: list[Transaction],
    *,
    min_ratio: float = 0.8,
    amount_tol: Decimal = Decimal("0.05"),
) -> list[MatchResult]:
    """Match on fuzzy reference similarity with a close-amount guard."""
    candidates: list[tuple[float, MatchResult]] = []
    for b in book:
        for s in source:
            if b.currency != s.currency:
                continue
            if abs(b.amount - s.amount) > amount_tol:
                continue
            bref = _norm_ref(b.reference)
            sref = _norm_ref(s.reference)
            if not bref or not sref:
                continue
            ratio = difflib.SequenceMatcher(None, bref, sref).ratio()
            if ratio < min_ratio:
                continue
            confidence = 0.65
            mr = MatchResult(
                book_txn_id=b.txn_id,
                source_txn_id=s.txn_id,
                match_type=MatchType.FUZZY,
                confidence=confidence,
                rule="fuzzy",
                rationale=(
                    f"reference similarity {ratio:.2f} "
                    f"('{b.reference}' vs '{s.reference}')"
                ),
                metadata={"similarity": round(ratio, 4)},
            )
            candidates.append((confidence, mr))
    return _greedy(candidates)
