"""Tests for B12: learning agent (mine matches/exceptions -> RuleSuggestions)."""

from __future__ import annotations

from reasoning.agents.learning_agent import learning_agent
from reasoning.rule_store import RuleStore
from reasoning.schemas import ExcType, ExceptionRecord, MatchResult, MatchType


def _match(book_id, source_id, rule, confidence=0.7, metadata=None):
    return MatchResult(
        book_txn_id=book_id,
        source_txn_id=source_id,
        match_type=MatchType.TOLERANCE if rule == "tolerance" else MatchType.FUZZY,
        confidence=confidence,
        rule=rule,
        metadata=metadata or {},
    )


def _exception(txn_id, exc_type, side="book"):
    return ExceptionRecord(
        txn_id=txn_id,
        side=side,
        exc_type=exc_type,
        risk_score=0.5,
        suggested_resolution="Investigate.",
    )


def test_recurring_tolerance_matches_suggest_widening():
    matches = [
        _match("b1", "s1", "tolerance", metadata={"amount_delta": "0.03"}),
        _match("b2", "s2", "tolerance", metadata={"amount_delta": "0.04"}),
    ]
    store = RuleStore()

    suggestions = learning_agent(matches, [], store=store)

    widen = next(s for s in suggestions if s.rule_type == "widen_tolerance")
    assert widen.support_count == 2
    assert widen.suggested_params["amount_tol"] == "0.04"
    assert len(store.pending()) == 1


def test_single_tolerance_match_does_not_suggest():
    matches = [_match("b1", "s1", "tolerance", metadata={"amount_delta": "0.03"})]
    suggestions = learning_agent(matches, [], store=RuleStore())
    assert not any(s.rule_type == "widen_tolerance" for s in suggestions)


def test_recurring_fuzzy_matches_suggest_lowering_threshold():
    matches = [
        _match("b1", "s1", "fuzzy", metadata={"similarity": 0.82}),
        _match("b2", "s2", "fuzzy", metadata={"similarity": 0.79}),
    ]
    suggestions = learning_agent(matches, [], store=RuleStore())

    lower = next(s for s in suggestions if s.rule_type == "lower_fuzzy_threshold")
    assert lower.support_count == 2
    assert lower.suggested_params["min_ratio"] == 0.79


def test_recurring_exception_type_suggests_pattern_review():
    exceptions = [
        _exception("b1", ExcType.TIMING),
        _exception("b2", ExcType.TIMING),
        _exception("b3", ExcType.FX),
    ]
    suggestions = learning_agent([], exceptions, store=RuleStore())

    pattern = next(s for s in suggestions if s.rule_type == "recurring_exception_pattern")
    assert pattern.support_count == 2
    assert pattern.suggested_params["exc_type"] == "timing"


def test_no_recurring_patterns_returns_empty_list():
    matches = [_match("b1", "s1", "tolerance", metadata={"amount_delta": "0.03"})]
    exceptions = [_exception("b2", ExcType.MISSING)]
    suggestions = learning_agent(matches, exceptions, store=RuleStore())
    assert suggestions == []


def test_suggestions_persisted_to_default_rule_store_when_none_given():
    from reasoning.rule_store import rule_store as global_store

    before = len(global_store.pending())
    matches = [
        _match("b1", "s1", "tolerance", metadata={"amount_delta": "0.03"}),
        _match("b2", "s2", "tolerance", metadata={"amount_delta": "0.02"}),
    ]
    learning_agent(matches, [])
    assert len(global_store.pending()) == before + 1
