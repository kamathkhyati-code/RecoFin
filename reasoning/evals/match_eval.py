"""Matching eval metrics + ablation harness (B15).

Ablation layers mirror how reasoning/match_subgraph.py actually composes:
  1. det_only            -- run_match_subgraph with no gateway, no memory.
  2. det_plus_llm         -- + a scripted LLM gateway (semantic escalation).
  3. det_plus_llm_plus_rag -- + match memory, pre-seeded with one prior
                              confirmed pair, so the confidence-calibration
                              boost (B7) is demonstrated deterministically
                              rather than asserted on faith.
"""
from __future__ import annotations

from datagents.schemas import Transaction
from recon_platform.gateway.llm_gateway import LLMGateway
from reasoning.agents.calibrated_matcher import (
    HallucinationError,
    guard_against_fabricated_ids,
)
from reasoning.match_subgraph import run_match_subgraph
from reasoning.memory.match_memory import MatchMemory
from reasoning.schemas import MatchResult, MatchType
from reasoning.thresholds import AUTO_MATCH_THRESHOLD as _PROVISIONAL_AUTO_THRESHOLD


class ScriptedSemanticGateway(LLMGateway):
    """Deterministic stand-in for a real LLM.

    Recognizes exactly the two reworded-reference pairs in the golden
    dataset (by a reference substring unique to each) and rejects
    everything else, so the ablation is fully reproducible without a
    live API call.
    """

    _KNOWN_MATCHES = {
        "XYZ123": 0.82,
        "REF-ALPHA-8": 0.82,
    }

    def _call(self, prompt: str) -> tuple[str, int, int]:
        for marker, confidence in self._KNOWN_MATCHES.items():
            if marker in prompt:
                text = (
                    '{"is_match": true, "confidence": %.2f, '
                    '"rationale": "same amount and counterparty, reworded reference (%s)"}'
                    % (confidence, marker)
                )
                return text, len(prompt.split()), 20
        text = (
            '{"is_match": false, "confidence": 0.05, '
            '"rationale": "no evidence of a shared payment"}'
        )
        return text, len(prompt.split()), 20


def precision_recall(
    matches: list[MatchResult], true_pairs: set[tuple[str, str]]
) -> tuple[float, float]:
    """Precision/recall of predicted (book_id, source_id) pairs vs ground truth."""
    predicted = {(m.book_txn_id, m.source_txn_id) for m in matches}
    precision = (len(predicted & true_pairs) / len(predicted)) if predicted else 1.0
    recall = (len(predicted & true_pairs) / len(true_pairs)) if true_pairs else 1.0
    return precision, recall


def auto_match_rate(
    matches: list[MatchResult], threshold: float = _PROVISIONAL_AUTO_THRESHOLD
) -> float:
    """Fraction of predicted matches confident enough to auto-apply."""
    if not matches:
        return 0.0
    autos = sum(1 for m in matches if m.confidence >= threshold)
    return autos / len(matches)


def hallucination_rate(
    matches: list[MatchResult], book: list[Transaction], source: list[Transaction]
) -> float:
    """1.0 if any match cites an id outside the candidate set, else 0.0."""
    try:
        guard_against_fabricated_ids(matches, book, source)
        return 0.0
    except HallucinationError:
        return 1.0


def _row(layer, matches, book, source, true_pairs, auto_threshold) -> dict:
    precision, recall = precision_recall(matches, true_pairs)
    return {
        "layer": layer,
        "matched_count": len(matches),
        "precision": round(precision, 4),
        "recall": round(recall, 4),
        "auto_match_rate": round(auto_match_rate(matches, auto_threshold), 4),
        "hallucination_rate": hallucination_rate(matches, book, source),
        "matches": matches,
    }


def run_ablation(
    book: list[Transaction],
    source: list[Transaction],
    true_pairs: set[tuple[str, str]],
    *,
    auto_threshold: float = _PROVISIONAL_AUTO_THRESHOLD,
    seed_pair_id: tuple[str, str] | None = None,
) -> list[dict]:
    """Run the matching pipeline through three layers and report metrics."""
    rows = []

    state1 = run_match_subgraph(
        {"book_transactions": book, "source_transactions": source}
    )
    rows.append(
        _row("det_only", state1["match_results"], book, source, true_pairs, auto_threshold)
    )

    state2 = run_match_subgraph(
        {"book_transactions": book, "source_transactions": source},
        gateway=ScriptedSemanticGateway(),
    )
    rows.append(
        _row(
            "det_plus_llm",
            state2["match_results"],
            book,
            source,
            true_pairs,
            auto_threshold,
        )
    )

    memory = MatchMemory(collection_name="b15_ablation_eval")
    if seed_pair_id is not None:
        book_by_id = {t.txn_id: t for t in book}
        source_by_id = {t.txn_id: t for t in source}
        b_id, s_id = seed_pair_id
        placeholder = MatchResult(
            book_txn_id=b_id,
            source_txn_id=s_id,
            match_type=MatchType.SEMANTIC,
            confidence=0.8,
            rule="seeded_history",
            rationale="pre-seeded prior confirmed match for ablation demo",
        )
        memory.upsert_match(book_by_id[b_id], source_by_id[s_id], placeholder)

    state3 = run_match_subgraph(
        {"book_transactions": book, "source_transactions": source},
        gateway=ScriptedSemanticGateway(),
        memory=memory,
    )
    rows.append(
        _row(
            "det_plus_llm_plus_rag",
            state3["match_results"],
            book,
            source,
            true_pairs,
            auto_threshold,
        )
    )

    return rows
