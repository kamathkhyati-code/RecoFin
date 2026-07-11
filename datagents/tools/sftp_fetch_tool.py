"""SFTP source tool (A3) — simulated SFTP fetch into an IngestResult.

No real SFTP connection (out of scope per plan's non-goals). Treats the
configured location as a local path standing in for a remote file, and
parses it with the same rules as the CSV tool.
"""
from __future__ import annotations

from datagents.schemas import IngestResult, SourceType
from datagents.tools.csv_read_tool import csv_read_tool
from recon_platform.state import IssueRecord


def sftp_fetch_tool(remote_path: str, source_name: str = "sftp") -> IngestResult:
    """Fetch and parse a transaction file from an SFTP source.

    For the prototype this reads a local file standing in for the remote
    one. Swapping in a real paramiko download later only changes how the
    file is obtained, not how it is parsed.
    """
    result = csv_read_tool(remote_path, source_name=source_name)

    # Re-tag parsed transactions as SFTP-sourced (csv_read_tool tags them CSV).
    for txn in result.transactions:
        txn.source = SourceType.SFTP

    if not result.transactions and not result.issues:
        result.issues.append(
            IssueRecord(
                source=source_name,
                severity="warning",
                message=f"No transactions found at {remote_path}",
            )
        )

    return result
