"""Tests for the B15 matching eval + ablation harness."""
from __future__ import annotations

import pytest

from reasoning.agents.calibrated_matcher import (
    HallucinationError,
    guard_against_fabricated_ids,
)
from reasoning.evals.golden_matching_dataset import build_golden_dataset
from reasoning.evals.match_eval import (
    auto_match_rate,
    precision_recall,
    run_ablation,
)
from reasoning.schemas import MatchResult, MatchType


def _fixture():
    return build_golden_dataset()


def test_det_only_misses_semantic_pairs():
    book, source, true_pairs, _, _ = _fixture()
    rows = run_ablation(book, source, true_pairs, seed_pair_id=("B-SM1", "S-SM1"))
    det = rows[0]
    matched_book_ids = {m.book_txn_id for m in det["matches"]}
    assert "B-SM1" not in matched_book_ids
    assert "B-SM2" not in matched_book_ids
    assert det["recall"] < 1.0
    assert det["precision"] == 1.0


def test_llm_layer_recovers_semantic_pairs():
    book, source, true_pairs, _, _ = _fixture()
    rows = run_ablation(book, source, true_pairs, seed_pair_id=("B-SM1", "S-SM1"))
    llm = rows[1]
    matched_pairs = {(m.book_txn_id, m.source_txn_id) for m in llm["matches"]}
    assert ("B-SM1", "S-SM1") in matched_pairs
    assert ("B-SM2", "S-SM2") in matched_pairs
    assert llm["recall"] == 1.0
    assert llm["precision"] == 1.0


def test_rag_layer_boosts_confidence_without_changing_recall():
    book, source, true_pairs, _, _ = _fixture()
    rows = run_ablation(book, source, true_pairs, seed_pair_id=("B-SM1", "S-SM1"))
    llm, rag = rows[1], rows[2]
    assert rag["recall"] == llm["recall"] == 1.0
    assert rag["matched_count"] == llm["matched_count"]

    def _confidence(row, book_id):
        return next(m.confidence for m in row["matches"] if m.book_txn_id == book_id)

    assert _confidence(rag, "B-SM1") > _confidence(llm, "B-SM1")
    assert rag["auto_match_rate"] >= llm["auto_match_rate"]


def test_precision_is_perfect_across_all_layers():
    book, source, true_pairs, _, _ = _fixture()
    rows = run_ablation(book, source, true_pairs, seed_pair_id=("B-SM1", "S-SM1"))
    for row in rows:
        assert row["precision"] == 1.0
        assert row["hallucination_rate"] == 0.0


def test_hallucination_guard_rejects_fabricated_id():
    book, source, _, _, _ = _fixture()
    fabricated = [
        MatchResult(
            book_txn_id="B-EX1",
            source_txn_id="DOES-NOT-EXIST",
            match_type=MatchType.SEMANTIC,
            confidence=0.9,
            rule="rigged",
            rationale="adversarial: fabricated source id",
        )
    ]
    with pytest.raises(HallucinationError):
        guard_against_fabricated_ids(fabricated, book, source)


def test_precision_recall_helper_on_empty_predictions():
    precision, recall = precision_recall([], {("A", "B")})
    assert precision == 1.0
    assert recall == 0.0


def test_auto_match_rate_helper():
    high = MatchResult(
        book_txn_id="B1",
        source_txn_id="S1",
        match_type=MatchType.EXACT,
        confidence=1.0,
        rule="exact",
    )
    low = MatchResult(
        book_txn_id="B2",
        source_txn_id="S2",
        match_type=MatchType.FUZZY,
        confidence=0.5,
        rule="fuzzy",
    )
    assert auto_match_rate([high, low], threshold=0.85) == 0.5
