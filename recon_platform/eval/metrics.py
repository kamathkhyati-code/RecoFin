"""Metric runners for the eval harness: accuracy and precision/recall."""

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
