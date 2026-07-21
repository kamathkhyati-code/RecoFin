"""Tests for C13: E2E baseline metrics."""

from __future__ import annotations

import json
import os
import tempfile
from datetime import date
from decimal import Decimal

from datagents.schemas import Currency, SourceType, Transaction
from recon_platform.eval.baseline import run_baseline


def _txn(txn_id, amount, ref, day=1, source=SourceType.CSV):
    return Transaction(
        txn_id=txn_id,
        date=date(2026, 6, day),
        amount=Decimal(amount),
        currency=Currency.USD,
        counterparty="ACME",
        reference=ref,
        source=source,
    )


def _golden_state():
    book = [
        _txn("B1", "100.00", "INV-001", day=1),
        _txn("B2", "200.00", "PAY-2", day=5),
        _txn("B3", "999.00", "NOPE", day=20),
    ]
    source = [
        _txn("S1", "100.00", "INV-001", day=1, source=SourceType.API),
        _txn("S2", "200.03", "PAY-2X", day=6, source=SourceType.API),
        _txn("S4", "555.00", "OTHER", day=25, source=SourceType.API),
    ]
    return {
        "run_id": "baseline-test-1",
        "period": "2026-06",
        "messages": [],
        "issues": [],
        "book_transactions": book,
        "source_transactions": source,
    }


def test_run_baseline_writes_report_with_real_metrics():
    with tempfile.TemporaryDirectory() as tmp:
        json_path, md_path = run_baseline(_golden_state(), tmp)

        assert os.path.exists(json_path)
        assert os.path.exists(md_path)

        with open(json_path) as f:
            payload = json.load(f)

        metrics = payload["metrics"]
        assert metrics["run_id"] == "baseline-test-1"
        assert metrics["matched_count"] == 2
        assert metrics["unmatched_count"] == 2
        assert metrics["exception_count"] == 2
        assert 0.0 < metrics["auto_match_rate"] < 1.0
        assert metrics["close_ready"] is False
        assert metrics["latency_ms"] > 0
        assert metrics["node_count"] > 0
        assert "generated_at" in payload


def test_run_baseline_default_label_is_run_id_scoped():
    with tempfile.TemporaryDirectory() as tmp:
        json_path, _ = run_baseline(_golden_state(), tmp)
        assert "baseline-test-1" in json_path


def test_run_baseline_distinct_runs_do_not_overwrite_each_other():
    with tempfile.TemporaryDirectory() as tmp:
        state_a = _golden_state()
        state_b = _golden_state()
        state_b["run_id"] = "baseline-test-2"

        json_path_a, _ = run_baseline(state_a, tmp)
        json_path_b, _ = run_baseline(state_b, tmp)

        assert json_path_a != json_path_b
        assert os.path.exists(json_path_a)
        assert os.path.exists(json_path_b)
