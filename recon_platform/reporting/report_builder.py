"""Reporting Agent -- packages a run's report into an exportable,
audit-ready artifact.

Distinct concern from consolidation_node (recon_platform/graph/build.py):
consolidation decides the summary numbers and close-readiness; this only
formats what consolidation already decided, plus the run's match/
exception/unmatched detail, into something an auditor or downstream
system can actually consume -- a JSON summary and per-table CSVs,
zippable into one download. Lives in recon_platform (not reasoning or
datagents) since it depends on types from both: Transaction (datagents)
and MatchResult/ExceptionRecord/ReconReport (reasoning), and
recon_platform is the shared platform layer both packages already depend
on (see ReconState's own docstring).
"""

from __future__ import annotations

import csv
import io
import json
import zipfile
from datetime import datetime, timezone

from datagents.schemas import Transaction
from reasoning.agents.exception_escalation import needs_escalation, sla_hours_for_risk
from reasoning.schemas import ExceptionRecord, MatchResult, ReconReport


def _txn_rows(txns: list[Transaction]) -> list[dict]:
    return [
        {
            "txn_id": t.txn_id,
            "date": t.date.isoformat(),
            "amount": str(t.amount),
            "currency": t.currency.value,
            "counterparty": t.counterparty,
            "reference": t.reference,
        }
        for t in txns
    ]


def _match_rows(matches: list[MatchResult]) -> list[dict]:
    return [
        {
            "book_txn_id": m.book_txn_id,
            "source_txn_id": m.source_txn_id,
            "match_type": m.match_type.value,
            "confidence": m.confidence,
            "rule": m.rule,
        }
        for m in matches
    ]


def _exception_rows(exceptions: list[ExceptionRecord]) -> list[dict]:
    return [
        {
            "txn_id": e.txn_id,
            "side": e.side,
            "exc_type": e.exc_type.value,
            "risk_score": e.risk_score,
            "suggested_resolution": e.suggested_resolution,
            "analyst_note": e.analyst_note,
            # SLA enforcement: only escalated (risk >= threshold) exceptions
            # actually land on the review queue and get a tracked deadline
            # -- auto-resolved ones never wait on a human, so "N/A" here is
            # correct, not a missing value.
            "sla_hours": sla_hours_for_risk(e.risk_score) if needs_escalation(e) else "N/A (auto-resolved)",
        }
        for e in exceptions
    ]


def _rows_to_csv_bytes(rows: list[dict]) -> bytes:
    """Empty list still produces a valid (headerless) CSV, not an error --
    a clean run with no unmatched items or exceptions is a real outcome,
    not a failure to package."""
    buf = io.StringIO()
    if rows:
        writer = csv.DictWriter(buf, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)
    return buf.getvalue().encode("utf-8")


def build_report_package(
    report: ReconReport,
    matches: list[MatchResult],
    unmatched_book: list[Transaction],
    unmatched_source: list[Transaction],
    exceptions: list[ExceptionRecord],
) -> dict:
    """Build the exportable artifact: a JSON-serializable summary dict plus
    per-table CSV bytes, ready to hand to a caller (e.g. demo_app.py's
    download button or a real audit pipeline) without that caller needing
    to know anything about the underlying pydantic schemas.
    """
    summary = {
        "run_id": report.run_id,
        "period": report.period,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "matched_count": report.matched_count,
        "unmatched_count": report.unmatched_count,
        "exception_count": report.exception_count,
        "match_rate": report.match_rate,
        "close_ready": report.close_ready,
    }
    return {
        "summary": summary,
        "matched_pairs_csv": _rows_to_csv_bytes(_match_rows(matches)),
        "unmatched_book_csv": _rows_to_csv_bytes(_txn_rows(unmatched_book)),
        "unmatched_source_csv": _rows_to_csv_bytes(_txn_rows(unmatched_source)),
        "exceptions_csv": _rows_to_csv_bytes(_exception_rows(exceptions)),
    }


def build_report_zip(package: dict) -> bytes:
    """Bundle build_report_package's output into a single downloadable
    zip -- the actual "audit-ready export" artifact."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("summary.json", json.dumps(package["summary"], indent=2))
        zf.writestr("matched_pairs.csv", package["matched_pairs_csv"])
        zf.writestr("unmatched_book.csv", package["unmatched_book_csv"])
        zf.writestr("unmatched_source.csv", package["unmatched_source_csv"])
        zf.writestr("exceptions.csv", package["exceptions_csv"])
    return buf.getvalue()
