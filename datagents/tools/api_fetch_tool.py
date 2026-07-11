"""API source tool (A3) — simulated API fetch into an IngestResult.

No real HTTP calls (out of scope per plan's non-goals). Accepts
pre-fetched records (e.g. from a mock/fixture) and validates them
the same way csv_read_tool does.
"""
from __future__ import annotations

from decimal import Decimal, InvalidOperation
from datetime import date

from datagents.schemas import IngestResult, SourceType, Transaction
from recon_platform.state import IssueRecord


def api_fetch_tool(records: list[dict], source_name: str = "api") -> IngestResult:
    """Parse a list of raw record dicts (as if returned by an API call) into an IngestResult.

    Each record dict is expected to have: txn_id, date (ISO), amount,
    currency, counterparty, reference (optional).
    """
    result = IngestResult(source_name=source_name)

    for i, row in enumerate(records, start=1):
        result.rows_read += 1
        try:
            txn = Transaction(
                txn_id=row["txn_id"],
                date=date.fromisoformat(row["date"]),
                amount=Decimal(str(row["amount"])),
                currency=row["currency"],
                counterparty=row["counterparty"],
                reference=row.get("reference") or None,
                source=SourceType.API,
            )
            result.transactions.append(txn)
        except (KeyError, ValueError, InvalidOperation) as e:
            result.issues.append(
                IssueRecord(
                    source=source_name,
                    severity="error",
                    message=f"Record {i} rejected: {e}",
                    row_ref=str(i),
                )
            )

    return result
