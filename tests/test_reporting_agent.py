"""Reporting Agent: packages a run's report into an exportable artifact.

Added after the boss's follow-up on the pitch deck check: "Reporting" was
listed as one of RecoFin's four agents but was previously just inline
consolidation logic with no export capability. This tests the standalone
reporting_node (wired after consolidation in build_graph) and the
underlying report_builder module directly.
"""

from __future__ import annotations

import csv
import io
import json
import zipfile
from datetime import date
from decimal import Decimal

from datagents.schemas import Currency, SourceType, Transaction
from recon_platform.graph.build import build_graph
from recon_platform.reporting.report_builder import build_report_package, build_report_zip
from reasoning.schemas import ExcType, ExceptionRecord, MatchResult, MatchType, ReconReport


def _txn(txn_id, amount, counterparty, ref, source=SourceType.CSV):
    return Transaction(
        txn_id=txn_id,
        date=date(2026, 6, 1),
        amount=Decimal(amount),
        currency=Currency.USD,
        counterparty=counterparty,
        reference=ref,
        source=source,
    )


def test_report_package_contains_summary_and_csv_tables():
    report = ReconReport(
        run_id="r1", period="2026-06", matched_count=1, unmatched_count=1,
        exception_count=1, match_rate=0.5, close_ready=False,
    )
    matches = [MatchResult(book_txn_id="B1", source_txn_id="S1", match_type=MatchType.EXACT, confidence=1.0, rule="exact")]
    unmatched_book = [_txn("B2", "50.00", "ACME", "INV-2")]
    unmatched_source = []
    exceptions = [ExceptionRecord(txn_id="B2", side="book", exc_type=ExcType.MISSING, risk_score=0.6, suggested_resolution="Investigate")]

    package = build_report_package(report, matches, unmatched_book, unmatched_source, exceptions)

    assert package["summary"]["run_id"] == "r1"
    assert package["summary"]["match_rate"] == 0.5
    assert package["summary"]["close_ready"] is False

    matched_rows = list(csv.DictReader(io.StringIO(package["matched_pairs_csv"].decode())))
    assert matched_rows == [{"book_txn_id": "B1", "source_txn_id": "S1", "match_type": "exact", "confidence": "1.0", "rule": "exact"}]

    unmatched_rows = list(csv.DictReader(io.StringIO(package["unmatched_book_csv"].decode())))
    assert unmatched_rows[0]["txn_id"] == "B2"

    exc_rows = list(csv.DictReader(io.StringIO(package["exceptions_csv"].decode())))
    assert exc_rows[0]["exc_type"] == "missing"


def test_report_package_handles_empty_tables_without_error():
    report = ReconReport(run_id="r2", period="2026-06", matched_count=0, unmatched_count=0, exception_count=0, match_rate=0.0, close_ready=True)
    package = build_report_package(report, [], [], [], [])
    assert package["matched_pairs_csv"] == b""
    assert package["summary"]["close_ready"] is True


def test_report_zip_contains_all_expected_files():
    report = ReconReport(run_id="r3", period="2026-06", matched_count=1, unmatched_count=0, exception_count=0, match_rate=1.0, close_ready=True)
    package = build_report_package(report, [], [], [], [])
    blob = build_report_zip(package)

    with zipfile.ZipFile(io.BytesIO(blob)) as zf:
        names = set(zf.namelist())
        assert names == {"summary.json", "matched_pairs.csv", "unmatched_book.csv", "unmatched_source.csv", "exceptions.csv"}
        summary = json.loads(zf.read("summary.json"))
        assert summary["run_id"] == "r3"


def test_reporting_node_is_reachable_through_real_graph():
    """Defect this closes: 'Reporting' was one of RecoFin's four pitched
    agents but had no standalone node and no export artifact -- just
    numbers computed inline by consolidation_node. Proves report_package
    is now populated by an actual graph run, not just the report_builder
    unit tests above."""
    book = [_txn("B1", "100.00", "ACME", "INV-1")]
    source = [_txn("S1", "100.00", "ACME", "INV-1", source=SourceType.API)]

    graph = build_graph()
    result = graph.invoke({
        "run_id": "reporting-agent-test",
        "period": "2026-06",
        "messages": [],
        "issues": [],
        "book_transactions": book,
        "source_transactions": source,
    })

    package = result.get("report_package")
    assert package is not None
    assert package["summary"]["run_id"] == "reporting-agent-test"
    assert package["summary"]["matched_count"] == 1

    role_values = [m.role.value for m in result["messages"]]
    assert "reporting" in role_values
