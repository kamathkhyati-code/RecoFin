"""Deterministic matching tools: exact, tolerance, fuzzy.

Each tool compares book vs source transactions and returns one-to-one
MatchResults (greedy, best-first within the tool). Every result carries a
confidence, a rule name, and a human-readable rationale. All three tools are
registered in the shared ToolRegistry so the matching agent can resolve them
by name (Architecture tab: run strategy tools strongest-first).

B17: candidates are found via bucketed/indexed lookups instead of full
n*m nested-loop scans, so this scales to 10k+ transactions per side --
exact_tool buckets by (currency, amount, date, reference) for O(n+m)
lookup; tolerance_tool and fuzzy_tool bucket by currency and binary-search
a sorted amount index for O((n+m) log m) candidate discovery. Normalized
reference strings are computed once per transaction and reused, instead of
being recomputed on every comparison (the "cache hot paths" step).

B19 (bug bash): duplicate transaction IDs within book or within source used
to cause a legitimate match to be silently dropped -- the greedy assigner
sees the id already "used" by an earlier candidate sharing that same
(duplicated) id and quietly skips the second one, with no error or
warning. That is a real reconciliation risk: a genuine match disappears
with no trace. Each tool now fails loudly instead, raising ValueError the
moment it sees a duplicate id in either input list.
"""
from __future__ import annotations

import bisect
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


def _assert_unique_ids(transactions: list[Transaction], label: str) -> None:
    """Fail loudly if `transactions` contains a duplicate txn_id.

    A duplicate id breaks the greedy assigner's one-match-per-id
    invariant: the second transaction sharing an id silently loses any
    match it would otherwise have gotten, with no error raised. That is
    a data-integrity problem upstream, not a matching decision, so it
    must never resolve silently.
    """
    seen: set[str] = set()
    for t in transactions:
        if t.txn_id in seen:
            raise ValueError(
                f"duplicate txn_id '{t.txn_id}' found in {label} transactions -- "
                "matching requires unique ids per side, otherwise a real match "
                "can be silently dropped"
            )
        seen.add(t.txn_id)


def _greedy(candidates: list[tuple[float, MatchResult]]) -> list[MatchResult]:
    """Assign candidates best-first, one book and one source txn each.

    Sorted by confidence descending, then by (book_txn_id, source_txn_id)
    as a deterministic tie-break -- this makes the result independent of
    the order candidates were discovered in, which matters once B17's
    bucketed lookups no longer produce candidates in strict nested-loop
    order.
    """
    used_book: set[str] = set()
    used_source: set[str] = set()
    out: list[MatchResult] = []
    ordered = sorted(
        candidates,
        key=lambda c: (-c[0], c[1].book_txn_id, c[1].source_txn_id),
    )
    for _, mr in ordered:
        if mr.book_txn_id in used_book or mr.source_txn_id in used_source:
            continue
        used_book.add(mr.book_txn_id)
        used_source.add(mr.source_txn_id)
        out.append(mr)
    return out


def _bucket_by_currency_sorted_amount(
    transactions: list[Transaction],
) -> dict:
    """Group transactions by currency, each group sorted by amount.

    Returns {currency: (sorted_transactions, sorted_amounts)} so callers
    can bisect the amounts list to find an amount-tolerance window in
    O(log m) instead of scanning every transaction.
    """
    by_currency: dict = {}
    for t in transactions:
        by_currency.setdefault(t.currency, []).append(t)
    out = {}
    for currency, txns in by_currency.items():
        txns_sorted = sorted(txns, key=lambda t: t.amount)
        out[currency] = (txns_sorted, [t.amount for t in txns_sorted])
    return out


@registry.register(
    "exact_tool",
    description="Match on identical currency, amount, date, and reference.",
)
def exact_tool(
    book: list[Transaction], source: list[Transaction]
) -> list[MatchResult]:
    """Match on identical currency, amount, date, and reference."""
    _assert_unique_ids(book, "book")
    _assert_unique_ids(source, "source")

    source_by_key: dict = {}
    for s in source:
        key = (s.currency, s.amount, s.date, _norm_ref(s.reference))
        source_by_key.setdefault(key, []).append(s)

    candidates: list[tuple[float, MatchResult]] = []
    for b in book:
        bref = _norm_ref(b.reference)
        if not bref:
            continue
        key = (b.currency, b.amount, b.date, bref)
        for s in source_by_key.get(key, []):
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
    _assert_unique_ids(book, "book")
    _assert_unique_ids(source, "source")

    buckets = _bucket_by_currency_sorted_amount(source)
    candidates: list[tuple[float, MatchResult]] = []

    for b in book:
        bucket = buckets.get(b.currency)
        if not bucket:
            continue
        txns_sorted, amounts = bucket
        lo = bisect.bisect_left(amounts, b.amount - amount_tol)
        hi = bisect.bisect_right(amounts, b.amount + amount_tol)
        for s in txns_sorted[lo:hi]:
            amt_delta = abs(b.amount - s.amount)
            if amt_delta > amount_tol:
                continue
            day_delta = abs((b.date - s.date).days)
            if day_delta > date_window:
                continue
            amt_score = 1.0 - float(amt_delta / amount_tol) if amount_tol else 1.0
            date_score = 1.0 - (day_delta / date_window) if date_window else 1.0
            confidence = round(0.6 + 0.35 * amt_score * date_score, 4)
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
    _assert_unique_ids(book, "book")
    _assert_unique_ids(source, "source")

    buckets = _bucket_by_currency_sorted_amount(source)
    source_norm_ref = {s.txn_id: _norm_ref(s.reference) for s in source}

    candidates: list[tuple[float, MatchResult]] = []
    for b in book:
        bref = _norm_ref(b.reference)
        if not bref:
            continue
        bucket = buckets.get(b.currency)
        if not bucket:
            continue
        txns_sorted, amounts = bucket
        lo = bisect.bisect_left(amounts, b.amount - amount_tol)
        hi = bisect.bisect_right(amounts, b.amount + amount_tol)
        for s in txns_sorted[lo:hi]:
            if abs(b.amount - s.amount) > amount_tol:
                continue
            sref = source_norm_ref[s.txn_id]
            if not sref:
                continue
            ratio = difflib.SequenceMatcher(None, bref, sref).ratio()
            if ratio < min_ratio:
                continue
            confidence = round(0.5 + 0.45 * ratio, 4)
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
