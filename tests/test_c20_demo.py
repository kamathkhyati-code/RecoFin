"""C20: final demo + handover -- eval dashboard tests."""

from __future__ import annotations

import os
import tempfile
from datetime import date
from decimal import Decimal
from pathlib import Path

from datagents.schemas import Currency, SourceType, Transaction
from recon_platform.eval.baseline import run_baseline
from recon_platform.eval.dashboard import render_dashboard

_SAMPLE_DIR = Path(__file__).resolve().parent.parent / "sample_data"


def _txn(txn_id, amount, ref, source=SourceType.CSV):
    return Transaction(
        txn_id=txn_id,
        date=date(2026, 6, 1),
        amount=Decimal(amount),
        currency=Currency.USD,
        counterparty="ACME",
        reference=ref,
        source=source,
    )


def test_dashboard_aggregates_multiple_real_baseline_runs():
    book = [_txn("B1", "100.00", "INV-1")]
    source = [_txn("S1", "100.00", "INV-1", source=SourceType.API)]
    state_template = {
        "period": "2026-06",
        "messages": [],
        "issues": [],
        "book_transactions": book,
        "source_transactions": source,
    }

    with tempfile.TemporaryDirectory() as tmp:
        json_paths = []
        for run_id in ("demo-run-1", "demo-run-2"):
            state = dict(state_template, run_id=run_id)
            json_path, _md_path = run_baseline(state, tmp)
            json_paths.append(json_path)

        dashboard_path = render_dashboard(json_paths, os.path.join(tmp, "dashboard.md"))

        assert os.path.exists(dashboard_path)
        content = open(dashboard_path).read()
        assert "demo-run-1" in content
        assert "demo-run-2" in content
        assert "2 run(s) aggregated" in content
        assert "Average auto-match rate" in content


def test_dashboard_handles_zero_reports():
    with tempfile.TemporaryDirectory() as tmp:
        path = render_dashboard([], os.path.join(tmp, "empty.md"))
        content = open(path).read()
        assert "0 run(s) aggregated" in content
