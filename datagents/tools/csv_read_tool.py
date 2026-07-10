"""CSV source tool (A3) — reads a CSV file into an IngestResult."""
from __future__ import annotations

import csv
from decimal import Decimal, InvalidOperation
from datetime import date

from datagents.schemas import IngestResult, SourceType, Transaction
from recon_platform.state import IssueRecord


def csv_read_tool(path: str, source_name: str = "csv") -> IngestResult:
    """Read transactions from a CSV file.

    Expected columns: txn_id, date (ISO), amount, currency, counterparty, reference (optional).
    Malformed rows are recorded as issues rather than raising.
    """
    result = IngestResult(source_name=source_name)

    try:
        with open(path, newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for i, row in enumerate(reader, start=1):
                result.rows_read += 1
                try:
                    txn = Transaction(
                        txn_id=row["txn_id"],
                        date=date.fromisoformat(row["date"]),
                        amount=Decimal(row["amount"]),
                        currency=row["currency"],
                        counterparty=row["counterparty"],
                        reference=row.get("reference") or None,
                        source=SourceType.CSV,
                    )
                    result.transactions.append(txn)
                except (KeyError, ValueError, InvalidOperation) as e:
                    result.issues.append(
                        IssueRecord(
                            source=source_name,
                            severity="error",
                            message=f"Row {i} rejected: {e}",
                            row_ref=str(i),
                        )
                    )
    except FileNotFoundError:
        result.issues.append(
            IssueRecord(
                source=source_name,
                severity="error",
                message=f"File not found: {path}",
            )
        )

    return result
