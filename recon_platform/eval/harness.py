"""Eval harness v0: runs an agent against a golden dataset and writes a report."""

from __future__ import annotations

from typing import Callable

from recon_platform.eval.dataset import GoldenRecord
from recon_platform.eval.metrics import accuracy, precision_recall
from recon_platform.eval.report import write_report


def run_eval(
    agent_fn: Callable[[dict], str],
    golden_records: list[GoldenRecord],
    output_dir: str,
    positive_label: str = "matched",
    run_label: str = "eval",
) -> tuple[str, str]:
    """Run agent_fn against every golden record, score it, and write a report.

    agent_fn takes a record's `input` dict and returns a predicted label
    string. Comparing predictions to expected_label produces accuracy and
    precision/recall for positive_label.
    """
    predictions = [agent_fn(record.input) for record in golden_records]
    labels = [record.expected_label for record in golden_records]

    metrics = {
        "accuracy": accuracy(predictions, labels),
        "precision_recall": precision_recall(predictions, labels, positive_label),
        "num_records": len(golden_records),
    }

    return write_report(metrics, output_dir, run_label)
