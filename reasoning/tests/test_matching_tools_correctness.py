"""Correctness cross-check for B17's optimized matching tools.

Compares the production tools (bucketed/indexed lookups) against
independent brute-force reference implementations (plain nested loops,
mirroring the pre-B17 logic) on randomized data, across several seeds.
If a bucketing optimization ever changed which pairs are found or their
confidence, this is what would catch it -- the fixed-fixture tests in
test_matching_tools.py wouldn't necessarily notice.
"""
from __future__ import annotations

import difflib
import random
from datetime import date, timedelta
from decimal import Decimal

from datagents.schemas import Currency, SourceType, Transaction
from reasoning.schemas import MatchResult, MatchType
from reasoning.tools.matching_tools import (
    _greedy,
    _norm_ref,
    exact_tool,
    fuzzy_tool,
    tolerance_tool,
)


def _random_transactions(
    seed: int, n: int
) -> tuple[list[Transaction], list[Transaction]]:
    """Randomized book/source pairs: exact-ish, tolerance-ish, fuzzy-ish, and noise."""
    rng = random.Random(seed)
    currencies = [Currency.USD, Currency.EUR]
    ref_words = ["Payment", "Invoice", "Settlement", "Transfer", "Order"]
    base_day = date(2026, 1, 1)
    book: list[Transaction] = []
    source: list[Transaction] = []

    for i in range(n):
        currency = rng.choice(currencies)
        amount = Decimal(rng.randint(1000, 999999)) / 100
        day_offset = rng.randint(0, 60)
        ref = f"{rng.choice(ref_words)} {rng.randint(1, 500)}"
        book.append(
            Transaction(
                txn_id=f"B{i}",
                date=base_day + timedelta(days=day_offset),
                amount=amount,
                currency=currency,
                counterparty="ACME",
                reference=ref,
                source=SourceType.CSV,
            )
        )
        variant = rng.random()
        if variant < 0.3:
            source.append(
                Transaction(
                    txn_id=f"S{i}",
                    date=base_day + timedelta(days=day_offset),
                    amount=amount,
                    currency=currency,
                    counterparty="ACME",
                    reference=ref,
                    source=SourceType.CSV,
                )
            )
        elif variant < 0.6:
            drift = Decimal(rng.randint(-4, 4)) / 100
            source.append(
                Transaction(
                    txn_id=f"S{i}",
                    date=base_day + timedelta(days=day_offset + rng.randint(-1, 1)),
                    amount=amount + drift,
                    currency=currency,
                    counterparty="ACME",
                    reference=ref + "X",
                    source=SourceType.CSV,
                )
            )
        elif variant < 0.8:
            source.append(
                Transaction(
                    txn_id=f"S{i}",
                    date=base_day + timedelta(days=day_offset),
                    amount=amount,
                    currency=currency,
                    counterparty="ACME",
                    reference=ref + " re: " + rng.choice(ref_words),
                    source=SourceType.CSV,
                )
            )
        else:
            source.append(
                Transaction(
                    txn_id=f"S{i}",
                    date=base_day + timedelta(days=rng.randint(0, 60)),
                    amount=Decimal(rng.randint(1000, 999999)) / 100,
                    currency=rng.choice(currencies),
                    counterparty="ACME",
                    reference=f"{rng.choice(ref_words)} {rng.randint(501, 999)}",
                    source=SourceType.CSV,
                )
            )
    return book, source


def _brute_exact(book, source):
    candidates = []
    for b in book:
        bref = _norm_ref(b.reference)
        if not bref:
            continue
        for s in source:
            if b.currency != s.currency or b.amount != s.amount or b.date != s.date:
                continue
            if bref != _norm_ref(s.reference):
                continue
            candidates.append(
                (
                    1.0,
                    MatchResult(
                        book_txn_id=b.txn_id,
                        source_txn_id=s.txn_id,
                        match_type=MatchType.EXACT,
                        confidence=1.0,
                        rule="exact",
                        rationale="brute-force reference",
                    ),
                )
            )
    return _greedy(candidates)


def _brute_tolerance(book, source, amount_tol=Decimal("0.05"), date_window=2):
    candidates = []
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
            amt_score = 1.0 - float(amt_delta / amount_tol) if amount_tol else 1.0
            date_score = 1.0 - (day_delta / date_window) if date_window else 1.0
            confidence = round(0.6 + 0.35 * amt_score * date_score, 4)
            candidates.append(
                (
                    confidence,
                    MatchResult(
                        book_txn_id=b.txn_id,
                        source_txn_id=s.txn_id,
                        match_type=MatchType.TOLERANCE,
                        confidence=confidence,
                        rule="tolerance",
                        rationale="brute-force reference",
                    ),
                )
            )
    return _greedy(candidates)


def _brute_fuzzy(book, source, min_ratio=0.8, amount_tol=Decimal("0.05")):
    candidates = []
    for b in book:
        bref = _norm_ref(b.reference)
        if not bref:
            continue
        for s in source:
            if b.currency != s.currency:
                continue
            if abs(b.amount - s.amount) > amount_tol:
                continue
            sref = _norm_ref(s.reference)
            if not sref:
                continue
            ratio = difflib.SequenceMatcher(None, bref, sref).ratio()
            if ratio < min_ratio:
                continue
            confidence = round(0.5 + 0.45 * ratio, 4)
            candidates.append(
                (
                    confidence,
                    MatchResult(
                        book_txn_id=b.txn_id,
                        source_txn_id=s.txn_id,
                        match_type=MatchType.FUZZY,
                        confidence=confidence,
                        rule="fuzzy",
                        rationale="brute-force reference",
                    ),
                )
            )
    return _greedy(candidates)


def _as_comparable(matches):
    """Order-independent (book_id, source_id, rule, confidence) tuples."""
    return sorted((m.book_txn_id, m.source_txn_id, m.rule, m.confidence) for m in matches)


def test_exact_tool_matches_brute_force_reference_across_seeds():
    for seed in (1, 2, 3, 4, 5):
        book, source = _random_transactions(seed, 150)
        assert _as_comparable(exact_tool(book, source)) == _as_comparable(
            _brute_exact(book, source)
        )


def test_tolerance_tool_matches_brute_force_reference_across_seeds():
    for seed in (1, 2, 3, 4, 5):
        book, source = _random_transactions(seed, 150)
        assert _as_comparable(tolerance_tool(book, source)) == _as_comparable(
            _brute_tolerance(book, source)
        )


def test_fuzzy_tool_matches_brute_force_reference_across_seeds():
    for seed in (1, 2, 3, 4, 5):
        book, source = _random_transactions(seed, 150)
        assert _as_comparable(fuzzy_tool(book, source)) == _as_comparable(
            _brute_fuzzy(book, source)
        )
