import json
import os
import tempfile

from recon_platform.eval.dataset import GoldenRecord, load_golden_dataset
from recon_platform.eval.metrics import accuracy, precision_recall
from recon_platform.eval.harness import run_eval


def stub_agent(input_dict: dict) -> str:
    """A stub agent: predicts 'matched' if amounts are equal, else 'unmatched'."""
    return "matched" if input_dict.get("amount_a") == input_dict.get("amount_b") else "unmatched"


def test_load_golden_dataset_from_json():
    with tempfile.TemporaryDirectory() as tmp:
        path = os.path.join(tmp, "golden.json")
        data = [
            {"record_id": "r1", "input": {"amount_a": 10, "amount_b": 10}, "expected_label": "matched"},
            {"record_id": "r2", "input": {"amount_a": 10, "amount_b": 20}, "expected_label": "unmatched"},
        ]
        with open(path, "w") as f:
            json.dump(data, f)

        records = load_golden_dataset(path)
        assert len(records) == 2
        assert records[0].record_id == "r1"
        assert records[0].expected_label == "matched"


def test_accuracy_all_correct():
    assert accuracy(["matched", "unmatched"], ["matched", "unmatched"]) == 1.0


def test_accuracy_partial():
    assert accuracy(["matched", "matched"], ["matched", "unmatched"]) == 0.5


def test_precision_recall_perfect():
    result = precision_recall(["matched", "unmatched"], ["matched", "unmatched"], "matched")
    assert result["precision"] == 1.0
    assert result["recall"] == 1.0
    assert result["f1"] == 1.0


def test_precision_recall_with_false_positive():
    result = precision_recall(["matched", "matched"], ["matched", "unmatched"], "matched")
    assert result["precision"] == 0.5
    assert result["recall"] == 1.0


def test_run_eval_against_stub_agent_writes_report_files():
    golden_records = [
        GoldenRecord(record_id="r1", input={"amount_a": 10, "amount_b": 10}, expected_label="matched"),
        GoldenRecord(record_id="r2", input={"amount_a": 10, "amount_b": 20}, expected_label="unmatched"),
        GoldenRecord(record_id="r3", input={"amount_a": 5, "amount_b": 5}, expected_label="matched"),
    ]

    with tempfile.TemporaryDirectory() as tmp:
        json_path, md_path = run_eval(stub_agent, golden_records, tmp, run_label="c9_test")

        assert os.path.exists(json_path)
        assert os.path.exists(md_path)

        with open(json_path) as f:
            payload = json.load(f)

        assert payload["metrics"]["accuracy"] == 1.0
        assert payload["metrics"]["num_records"] == 3
