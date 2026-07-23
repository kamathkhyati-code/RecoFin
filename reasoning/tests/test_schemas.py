"""Tests for reasoning schemas: bounds enforcement and enum coercion."""
from __future__ import annotations

import pytest
from pydantic import ValidationError

from reasoning.schemas import (
    ExceptionRecord,
    ExcType,
    MatchResult,
    MatchType,
    ReconReport,
    RuleSuggestion,
)


def _mr(**kw):
    base = {
        "book_txn_id": "B1",
        "source_txn_id": "S1",
        "match_type": "exact",
        "confidence": 0.9,
        "rule": "exact_id",
    }
    base.update(kw)
    return MatchResult(**base)


def test_matchresult_enum_coercion():
    assert _mr(match_type="tolerance").match_type is MatchType.TOLERANCE


def test_matchresult_bad_enum_raises():
    with pytest.raises(ValidationError):
        _mr(match_type="banana")


def test_matchresult_confidence_upper_bound():
    with pytest.raises(ValidationError):
        _mr(confidence=1.5)


def test_matchresult_confidence_lower_bound():
    with pytest.raises(ValidationError):
        _mr(confidence=-0.1)


def test_matchresult_confidence_bounds_ok():
    assert _mr(confidence=0.0).confidence == 0.0
    assert _mr(confidence=1.0).confidence == 1.0


def test_exceptionrecord_enum_coercion_and_default():
    exc = ExceptionRecord(txn_id="B9", side="book", exc_type="fx")
    assert exc.exc_type is ExcType.FX
    assert ExceptionRecord(txn_id="B9", side="book").exc_type is ExcType.UNKNOWN


def test_exceptionrecord_risk_bounds():
    with pytest.raises(ValidationError):
        ExceptionRecord(txn_id="B9", side="book", risk_score=2.0)


def test_rulesuggestion_confidence_bounds():
    with pytest.raises(ValidationError):
        RuleSuggestion(rule_type="widen_tolerance", description="x", confidence=9.0)


def test_reconreport_defaults():
    rep = ReconReport(run_id="r1", period="2026-06")
    assert rep.matched_count == 0
    assert rep.close_ready is False
