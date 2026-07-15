"""Golden dataset loader for the eval harness."""

from __future__ import annotations

import json
from dataclasses import dataclass


@dataclass
class GoldenRecord:
    """One labeled example: an input plus the expected outcome."""

    record_id: str
    input: dict
    expected_label: str


def load_golden_dataset(path: str) -> list[GoldenRecord]:
    """Load a golden dataset from a JSON file.

    Expected format: a list of objects, each with "record_id",
    "input" (arbitrary dict), and "expected_label".
    """
    with open(path) as f:
        raw = json.load(f)

    return [
        GoldenRecord(
            record_id=item["record_id"],
            input=item["input"],
            expected_label=item["expected_label"],
        )
        for item in raw
    ]
