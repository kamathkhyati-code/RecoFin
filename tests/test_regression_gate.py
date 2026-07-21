"""C15: eval harness v1 -- CI regression gate.

Runs accuracy, hallucination-rate, idempotency, and latency checks
against golden data with hard-coded minimum thresholds. A regression in
any of these fails this test, which fails CI (.github/workflows/ci.yml
runs `pytest datagents/ reasoning/ tests/ -v` on every push/PR) -- no
separate CI config needed, this test *is* the gate. Branch protection
requiring CI to pass before merge is what turns "test fails" into
"merge is blocked"; that's a GitHub repo setting, not something a test
file can configure.
"""

from __future__ import annotations

import os
import tempfile
from datetime import date
from decimal import Decimal

from datagents.schemas import Currency, SourceType, Transaction
from reasoning.agents.matching_agent import run_matching
from recon_platform.eval.baseline import run_baseline
from recon_platform.eval.metrics import accuracy, hallucination_rate, idempotency_check

_MIN_MATCH_ACCURACY = 0.9
_MAX_HALLUCINATION_RATE = 0.0
_MAX_E2E_LATENCY_MS = 2000  # generous budget; catches catastrophic regressions, not noise


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


def _golden_matching_fixture():
    book = [
        _txn("B1", "100.00", "INV-001", day=1),
        _txn("B2", "200.00", "PAY-2", day=5),
        _txn("B3", "300.00", "Payment for invoice 300", day=10),
        _txn("B4", "999.00", "NOPE", day=20),
    ]
    source = [
        _txn("S1", "100.00", "INV-001", day=1, source=SourceType.API),
        _txn("S2", "200.03", "PAY-2X", day=6, source=SourceType.API),
        _txn("S3", "300.00", "Payment for invoice #300", day=25, source=SourceType.API),
        _txn("S4", "555.00", "OTHER", day=25, source=SourceType.API),
    ]
    expected_labels = {
        "B1": "matched", "B2": "matched", "B3": "matched", "B4": "unmatched",
        "S1": "matched", "S2": "matched", "S3": "matched", "S4": "unmatched",
    }
    return book, source, expected_labels


def test_matching_accuracy_meets_baseline():
    book, source, expected_labels = _golden_matching_fixture()
    matches, _, _ = run_matching(book, source)

    matched_ids = {m.book_txn_id for m in matches} | {m.source_txn_id for m in matches}
    predictions = [
        "matched" if txn_id in matched_ids else "unmatched" for txn_id in expected_labels
    ]
    labels = list(expected_labels.values())

    assert accuracy(predictions, labels) >= _MIN_MATCH_ACCURACY


def test_hallucination_rate_is_zero_on_deterministic_matches():
    book, source, _ = _golden_matching_fixture()
    matches, _, _ = run_matching(book, source)

    valid_book_ids = {t.txn_id for t in book}
    valid_source_ids = {t.txn_id for t in source}

    assert hallucination_rate(matches, valid_book_ids, valid_source_ids) <= _MAX_HALLUCINATION_RATE


def test_idempotent_reruns_are_skipped():
    with tempfile.TemporaryDirectory() as tmp:
        db_path = os.path.join(tmp, "checkpoints.db")
        assert idempotency_check("2026-06", "golden-v1", db_path) is True


def test_e2e_latency_within_budget():
    book, source, _ = _golden_matching_fixture()
    with tempfile.TemporaryDirectory() as tmp:
        json_path, _ = run_baseline(
            {
                "run_id": "regression-gate-latency",
                "period": "2026-06",
                "messages": [],
                "issues": [],
                "book_transactions": book,
                "source_transactions": source,
            },
            tmp,
        )
        import json

        with open(json_path) as f:
            payload = json.load(f)

        assert payload["metrics"]["latency_ms"] < _MAX_E2E_LATENCY_MS
