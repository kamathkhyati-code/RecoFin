"""API source tool (A3) — fetches transactions over HTTP into an IngestResult.

Makes a real HTTP GET via httpx. Tests point it at a mock server served on
localhost, so the HTTP path is genuinely exercised without hitting a live
bank/ERP endpoint (out of scope per the plan's non-goals).
"""
from __future__ import annotations

from datetime import date
from decimal import Decimal, InvalidOperation

import httpx

from datagents.schemas import IngestResult, SourceType, Transaction
from recon_platform.registry import registry
from recon_platform.state import IssueRecord


def _parse_records(records: list[dict], source_name: str) -> IngestResult:
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


@registry.register(
    "api_fetch_tool",
    description="Fetch transactions from an HTTP API endpoint into an IngestResult.",
)
def api_fetch_tool(
    endpoint: str,
    source_name: str = "api",
    timeout: float = 5.0,
) -> IngestResult:
    """GET transactions from an API endpoint and parse them.

    A failed request is recorded as an error issue rather than raising, so one
    dead source cannot take down the whole ingestion run.
    """
    try:
        response = httpx.get(endpoint, timeout=timeout)
        response.raise_for_status()
        records = response.json()
    except (httpx.HTTPError, ValueError) as e:
        result = IngestResult(source_name=source_name)
        result.issues.append(
            IssueRecord(
                source=source_name,
                severity="error",
                message=f"API fetch failed for {endpoint}: {e}",
            )
        )
        return result

    if not isinstance(records, list):
        result = IngestResult(source_name=source_name)
        result.issues.append(
            IssueRecord(
                source=source_name,
                severity="error",
                message=f"API returned {type(records).__name__}, expected a list of records",
            )
        )
        return result

    return _parse_records(records, source_name)
