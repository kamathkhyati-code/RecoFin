from datetime import date
from decimal import Decimal

import pytest

from datagents.schemas import Currency, SourceType, Transaction
from reasoning.agents.calibrated_matcher import (
    HallucinationError,
    calibrate_confidence,
    guard_against_fabricated_ids,
)
from reasoning.schemas import MatchResult, MatchType


def _txn(txn_id, amount="100.00", reference="Ref", source=SourceType.CSV):
    return Transaction(
        txn_id=txn_id,
        date=date(2026, 6, 1),
        amount=Decimal(amount),
        currency=Currency.USD,
        counterparty="Acme Corp",
        reference=reference,
        source=source,
    )


def _match(book_id, source_id, confidence=0.8):
    return MatchResult(
        book_txn_id=book_id,
        source_txn_id=source_id,
        match_type=MatchType.SEMANTIC,
        confidence=confidence,
        rule="semantic_llm",
    )


def test_guard_rejects_fabricated_book_id():
    book = [_txn("b1")]
    source = [_txn("s1", source=SourceType.API)]
    matches = [_match("b_FAKE", "s1")]

    with pytest.raises(HallucinationError, match="b_FAKE"):
        guard_against_fabricated_ids(matches, book, source)


def test_guard_rejects_fabricated_source_id():
    book = [_txn("b1")]
    source = [_txn("s1", source=SourceType.API)]
    matches = [_match("b1", "s_FAKE")]

    with pytest.raises(HallucinationError, match="s_FAKE"):
        guard_against_fabricated_ids(matches, book, source)


def test_guard_allows_legitimate_ids():
    book = [_txn("b1")]
    source = [_txn("s1", source=SourceType.API)]
    matches = [_match("b1", "s1")]

    result = guard_against_fabricated_ids(matches, book, source)
    assert result == matches


def test_calibration_no_memory_hits_returns_raw_confidence():
    match = _match("b1", "s1", confidence=0.8)
    assert calibrate_confidence(match, []) == 0.8


def test_calibration_distant_memory_hit_does_not_boost():
    match = _match("b1", "s1", confidence=0.8)
    hits = [{"distance": 0.9, "metadata": {}}]
    assert calibrate_confidence(match, hits) == 0.8
