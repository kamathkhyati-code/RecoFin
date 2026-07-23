"""Tests for API and SFTP source tools (A3).

The API test serves a mock endpoint on localhost so the real httpx path runs.
The SFTP test injects a fake sftp client so the paramiko path is bypassed
without a live server.
"""
from __future__ import annotations

import json
import threading
from decimal import Decimal
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

from datagents.schemas import SourceType
from datagents.tools.api_fetch_tool import api_fetch_tool
from datagents.tools.sftp_fetch_tool import sftp_fetch_tool
from recon_platform.registry import registry

VALID_RECORDS = [
    {"txn_id": "A1", "date": "2026-01-15", "amount": "250.75",
     "currency": "USD", "counterparty": "ACME Corp", "reference": "INV-9"},
    {"txn_id": "A2", "date": "2026-01-16", "amount": -40,
     "currency": "gbp", "counterparty": "Globex"},
]

BAD_RECORDS = [
    {"txn_id": "A1", "date": "2026-01-15", "amount": "10.00",
     "currency": "USD", "counterparty": "ACME"},
    {"txn_id": "A2", "date": "2026-01-16", "amount": "20.00",
     "currency": "TOOLONG", "counterparty": "Globex"},
]


def _make_handler(payload):
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):  # noqa: N802 - http.server API
            body = json.dumps(payload).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *args):  # silence test output
            pass

    return Handler


@pytest.fixture
def mock_api():
    """Serve a records payload on localhost; yields a factory taking the payload."""
    servers = []

    def _serve(payload):
        server = HTTPServer(("127.0.0.1", 0), _make_handler(payload))
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        servers.append(server)
        host, port = server.server_address
        return f"http://{host}:{port}/transactions"

    yield _serve

    for server in servers:
        server.shutdown()


class FakeSFTPClient:
    """Stands in for paramiko's SFTPClient in tests."""

    def __init__(self, contents: str | None = None, fail: bool = False):
        self._contents = contents
        self._fail = fail

    def get(self, remote_path: str, local_path: str) -> None:
        if self._fail:
            raise OSError(f"no such file: {remote_path}")
        with open(local_path, "w", encoding="utf-8") as f:
            f.write(self._contents or "")


def test_api_fetches_from_localhost_mock(mock_api):
    endpoint = mock_api(VALID_RECORDS)

    result = api_fetch_tool(endpoint, source_name="erp")

    assert result.rows_read == 2
    assert len(result.transactions) == 2
    assert result.transactions[0].amount == Decimal("250.75")
    assert result.transactions[1].currency == "GBP"  # normalized
    assert result.transactions[0].source == SourceType.API
    assert result.ok is True


def test_api_flags_bad_record(mock_api):
    endpoint = mock_api(BAD_RECORDS)

    result = api_fetch_tool(endpoint, source_name="erp")

    assert result.rows_read == 2
    assert len(result.transactions) == 1
    assert len(result.issues) == 1
    assert result.ok is False


def test_api_unreachable_endpoint_is_an_issue():
    # Port 1 is reserved and will refuse the connection.
    result = api_fetch_tool("http://127.0.0.1:1/transactions", source_name="erp")

    assert result.transactions == []
    assert len(result.issues) == 1
    assert result.ok is False


def test_sftp_downloads_and_tags_source(tmp_path):
    client = FakeSFTPClient(
        "txn_id,date,amount,currency,counterparty,reference\n"
        "S1,2026-01-15,99.99,EUR,Initech,REF-1\n"
    )

    result = sftp_fetch_tool(
        host="sftp.example.com",
        remote_path="/out/txns.csv",
        source_name="bank_sftp",
        local_dir=str(tmp_path),
        sftp_client=client,
    )

    assert result.rows_read == 1
    assert len(result.transactions) == 1
    assert result.transactions[0].source == SourceType.SFTP  # re-tagged, not CSV
    assert result.ok is True


def test_sftp_download_failure_is_an_issue(tmp_path):
    client = FakeSFTPClient(fail=True)

    result = sftp_fetch_tool(
        host="sftp.example.com",
        remote_path="/out/missing.csv",
        source_name="bank_sftp",
        local_dir=str(tmp_path),
        sftp_client=client,
    )

    assert result.transactions == []
    assert len(result.issues) == 1
    assert result.ok is False


def test_all_three_tools_registered():
    import datagents.tools.csv_read_tool  # noqa: F401 - registers on import

    tools = registry.list_tools()
    assert "csv_read_tool" in tools
    assert "api_fetch_tool" in tools
    assert "sftp_fetch_tool" in tools
