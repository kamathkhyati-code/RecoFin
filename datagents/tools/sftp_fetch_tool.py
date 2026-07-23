"""SFTP source tool (A3) — downloads a remote file via paramiko, then parses it.

Uses a real paramiko SSHClient/SFTPClient. Tests inject a mock client so the
paramiko code path is exercised without a live SFTP server (out of scope per
the plan's non-goals).
"""
from __future__ import annotations

from pathlib import Path

import paramiko

from datagents.schemas import IngestResult, SourceType
from datagents.tools.csv_read_tool import csv_read_tool
from recon_platform.registry import registry
from recon_platform.state import IssueRecord


def _download_via_paramiko(
    host: str,
    remote_path: str,
    local_path: str,
    username: str,
    password: str,
    port: int,
) -> None:
    """Open an SFTP connection and pull the remote file down to local_path."""
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    try:
        client.connect(
            hostname=host, port=port, username=username, password=password, timeout=10
        )
        sftp = client.open_sftp()
        try:
            sftp.get(remote_path, local_path)
        finally:
            sftp.close()
    finally:
        client.close()


@registry.register(
    "sftp_fetch_tool",
    description="Download a transaction file over SFTP (paramiko) and parse it.",
)
def sftp_fetch_tool(
    host: str,
    remote_path: str,
    source_name: str = "sftp",
    username: str = "",
    password: str = "",
    port: int = 22,
    local_dir: str = ".sftp_staging",
    sftp_client: object | None = None,
    field_map: dict[str, str] | None = None,
) -> IngestResult:
    """Fetch a transaction file from an SFTP host and parse it.

    If sftp_client is supplied (tests), its .get(remote, local) is used instead
    of opening a real connection. A failed transfer is recorded as an error
    issue rather than raising.
    """
    staging = Path(local_dir)
    staging.mkdir(parents=True, exist_ok=True)
    local_path = staging / Path(remote_path).name

    try:
        if sftp_client is not None:
            sftp_client.get(remote_path, str(local_path))
        else:
            _download_via_paramiko(
                host, remote_path, str(local_path), username, password, port
            )
    except Exception as e:  # noqa: BLE001 - any transfer failure is an ingestion issue
        result = IngestResult(source_name=source_name)
        result.issues.append(
            IssueRecord(
                source=source_name,
                severity="error",
                message=f"SFTP download failed from {host}:{remote_path}: {e}",
            )
        )
        return result

    result = csv_read_tool(
        str(local_path), source_name=source_name, field_map=field_map
    )

    for txn in result.transactions:
        txn.source = SourceType.SFTP

    return result
