"""Confidence calibration and hallucination guard - B7.

Two responsibilities:

1. Hallucination guard: a matcher must never emit a MatchResult whose
   book_txn_id or source_txn_id was not in the candidate set it was given.
   An LLM that fabricates an ID is rejected outright, never trusted.

2. Calibration: blend the raw model confidence with memory support (from
   B6's match_memory). A pair the memory has seen before is boosted; a
   pair with no historical support keeps the raw confidence.
"""

from __future__ import annotations

from datagents.schemas import Transaction
from reasoning.schemas import MatchResult


class HallucinationError(Exception):
    """Raised when a MatchResult references a transaction id not in the candidate set."""


def guard_against_fabricated_ids(
    matches: list[MatchResult],
    book: list[Transaction],
    source: list[Transaction],
) -> list[MatchResult]:
    """Reject any match citing a book/source id that was never a candidate.

    Returns the matches unchanged if all ids are legitimate; raises
    HallucinationError on the first fabricated id found.
    """
    valid_book = {t.txn_id for t in book}
    valid_source = {t.txn_id for t in source}

    for match in matches:
        if match.book_txn_id not in valid_book:
            raise HallucinationError(
                f"Fabricated book_txn_id '{match.book_txn_id}' not in candidate set."
            )
        if match.source_txn_id not in valid_source:
            raise HallucinationError(
                f"Fabricated source_txn_id '{match.source_txn_id}' not in candidate set."
            )

    return matches


# A memory hit closer than this distance counts as genuine historical support.
_SUPPORT_DISTANCE_THRESHOLD = 0.15

# How much a memory hit can lift raw confidence, capped so memory never
# manufactures certainty on its own.
_MAX_MEMORY_BOOST = 0.15


def calibrate_confidence(
    match: MatchResult,
    memory_hits: list[dict],
    support_threshold: float = _SUPPORT_DISTANCE_THRESHOLD,
    max_boost: float = _MAX_MEMORY_BOOST,
) -> float:
    """Blend raw confidence with memory support, clamped to [0, 1].

    memory_hits is the output of match_memory.retrieve_nearest: dicts with
    a "distance" key (lower = more similar). If the nearest hit is within
    support_threshold, confidence is boosted proportionally to how close
    it is; otherwise raw confidence is returned unchanged.
    """
    raw = match.confidence
    if not memory_hits:
        return raw

    nearest = min(hit["distance"] for hit in memory_hits if hit.get("distance") is not None)
    if nearest > support_threshold:
        return raw

    closeness = 1.0 - (nearest / support_threshold)
    calibrated = raw + max_boost * closeness
    return max(0.0, min(1.0, calibrated))


def calibrate_matches(
    matches: list[MatchResult],
    book: list[Transaction],
    source: list[Transaction],
    memory=None,
) -> list[MatchResult]:
    """Guard against fabricated ids, then calibrate each match's confidence.

    Guarding happens first: a fabricated id fails loudly before any
    calibration. If a memory store is provided, each surviving match's
    confidence is recalibrated against its nearest historical neighbours.
    """
    guarded = guard_against_fabricated_ids(matches, book, source)
    if memory is None:
        return guarded

    book_by_id = {t.txn_id: t for t in book}
    source_by_id = {t.txn_id: t for t in source}

    calibrated: list[MatchResult] = []
    for match in guarded:
        hits = memory.retrieve_nearest(
            book_by_id[match.book_txn_id], source_by_id[match.source_txn_id], n_results=3
        )
        new_conf = calibrate_confidence(match, hits)
        calibrated.append(match.model_copy(update={"confidence": new_conf}))

    return calibrated
