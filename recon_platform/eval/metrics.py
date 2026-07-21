"""Metric runners for the eval harness: accuracy, precision/recall,
hallucination rate, and idempotency (C15)."""

from __future__ import annotations


def accuracy(predictions: list[str], labels: list[str]) -> float:
    if not predictions:
        return 0.0
    correct = sum(1 for pred, label in zip(predictions, labels) if pred == label)
    return correct / len(predictions)


def precision_recall(predictions: list[str], labels: list[str], positive_label: str) -> dict:
    """Precision/recall/F1 for a single positive_label, treated as binary."""
    tp = sum(1 for pred, label in zip(predictions, labels) if pred == positive_label and label == positive_label)
    fp = sum(1 for pred, label in zip(predictions, labels) if pred == positive_label and label != positive_label)
    fn = sum(1 for pred, label in zip(predictions, labels) if pred != positive_label and label == positive_label)

    precision = tp / (tp + fp) if (tp + fp) > 0 else 0.0
    recall = tp / (tp + fn) if (tp + fn) > 0 else 0.0
    f1 = (2 * precision * recall / (precision + recall)) if (precision + recall) > 0 else 0.0

    return {"precision": precision, "recall": recall, "f1": f1}


def hallucination_rate(matches: list, valid_book_ids: set[str], valid_source_ids: set[str]) -> float:
    """Fraction of matches referencing a book/source id outside the valid candidate set.

    B7's calibrate_matches already guards against this at the point a
    match is produced (raises HallucinationError), so a healthy
    deterministic pipeline always scores 0.0 here. This makes that
    guarantee measurable and regression-testable rather than just
    trusted, especially once the LLM path (B5) is exercised for real.

    Duck-typed on .book_txn_id/.source_txn_id so this module doesn't need
    to import reasoning.schemas.MatchResult directly.
    """
    if not matches:
        return 0.0
    bad = sum(
        1
        for m in matches
        if m.book_txn_id not in valid_book_ids or m.source_txn_id not in valid_source_ids
    )
    return bad / len(matches)


def idempotency_check(period: str, source_signature: str, db_path: str) -> bool:
    """True if running the same (period, source_signature) twice is safe.

    Reuses C4's run_pipeline skip-if-complete mechanism directly rather
    than reinventing the check: the first run processes normally, the
    second must be skipped (not reprocessed) and report the same run_id.
    """
    from recon_platform.graph.checkpointer import get_checkpointer, run_pipeline

    with get_checkpointer(db_path) as cp:
        first = run_pipeline(period, source_signature, cp)
        second = run_pipeline(period, source_signature, cp)

    return second["skipped"] is True and first["run_id"] == second["run_id"]
