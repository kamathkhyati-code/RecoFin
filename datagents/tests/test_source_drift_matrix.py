"""A12: Multi-source robustness -- schema-drift matrix across all 3 source
types (CSV, API, SFTP).

Each source tool already has its own focused unit tests (test_csv_read_tool,
test_api_sftp_tools). This file adds the thing A12 actually asks for and none
of those cover explicitly: the SAME set of schema-drift/missing-field
scenarios run against all three transports, so we know they behave
consistently rather than "probably the same since they share code."

Scenarios per source type:
  1. canonical field names, everything present            -> 1 txn, 0 issues
  2. optional field's column/key entirely absent           -> 1 txn, 0 issues (reference=None)
  3. required field renamed + field_map supplied           -> 1 txn, 0 issues
  4. required field renamed, no field_map supplied         -> 0 txn, 1 issue (rejected, not a crash)
  5. required field's column/key entirely missing          -> 0 txn, 1 issue (rejected, not a crash)

"No crash" is the acceptance criterion, so every scenario asserts the call
returns a normal IngestResult rather than raising.
"""
from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

from datagents.tools.api_fetch_tool import api_fetch_tool
from datagents.tools.csv_read_tool import csv_read_tool
from datagents.tools.sftp_fetch_tool import sftp_fetch_tool


# ---- shared fixtures (same pattern as test_api_sftp_tools.py) ----


def _make_handler(payload):
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):  # noqa: N802 - http.server API
            body = json.dumps(payload).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *args):
            pass

    return Handler


@pytest.fixture
def mock_api():
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
    def __init__(self, contents: str | None = None):
        self._contents = contents

    def get(self, remote_path: str, local_path: str) -> None:
        with open(local_path, "w", encoding="utf-8") as f:
            f.write(self._contents or "")


# ---- CSV: drift matrix ----


def test_csv_canonical_fields_all_present(tmp_path):
    f = tmp_path / "t.csv"
    f.write_text(
        "txn_id,date,amount,currency,counterparty,reference\n"
        "T1,2026-01-01,100.00,USD,ACME,INV-1\n"
    )
    result = csv_read_tool(str(f), source_name="s")
    assert len(result.transactions) == 1
    assert result.issues == []


def test_csv_optional_reference_column_entirely_absent(tmp_path):
    f = tmp_path / "t.csv"
    f.write_text(
        "txn_id,date,amount,currency,counterparty\n"  # no reference column at all
        "T1,2026-01-01,100.00,USD,ACME\n"
    )
    result = csv_read_tool(str(f), source_name="s")
    assert len(result.transactions) == 1
    assert result.transactions[0].reference is None
    assert result.issues == []


def test_csv_renamed_required_field_with_map(tmp_path):
    f = tmp_path / "t.csv"
    f.write_text(
        "transaction_id,date,amount,currency,counterparty,reference\n"
        "T1,2026-01-01,100.00,USD,ACME,INV-1\n"
    )
    result = csv_read_tool(str(f), source_name="s", field_map={"transaction_id": "txn_id"})
    assert len(result.transactions) == 1
    assert result.issues == []


def test_csv_renamed_required_field_without_map_is_rejected_not_a_crash(tmp_path):
    f = tmp_path / "t.csv"
    f.write_text(
        "transaction_id,date,amount,currency,counterparty,reference\n"
        "T1,2026-01-01,100.00,USD,ACME,INV-1\n"
    )
    result = csv_read_tool(str(f), source_name="s")  # no field_map
    assert result.transactions == []
    assert len(result.issues) == 1
    assert result.issues[0].severity == "error"


def test_csv_required_field_column_entirely_missing_is_rejected_not_a_crash(tmp_path):
    f = tmp_path / "t.csv"
    f.write_text(
        "txn_id,date,amount,currency\n"  # counterparty column entirely missing
        "T1,2026-01-01,100.00,USD\n"
    )
    result = csv_read_tool(str(f), source_name="s")
    assert result.transactions == []
    assert len(result.issues) == 1
    assert result.issues[0].severity == "error"


# ---- API: drift matrix ----


def test_api_canonical_fields_all_present(mock_api):
    endpoint = mock_api([
        {"txn_id": "A1", "date": "2026-01-01", "amount": "100.00",
         "currency": "USD", "counterparty": "ACME", "reference": "INV-1"},
    ])
    result = api_fetch_tool(endpoint, source_name="s")
    assert len(result.transactions) == 1
    assert result.issues == []


def test_api_optional_reference_key_entirely_absent(mock_api):
    endpoint = mock_api([
        {"txn_id": "A1", "date": "2026-01-01", "amount": "100.00",
         "currency": "USD", "counterparty": "ACME"},  # no "reference" key at all
    ])
    result = api_fetch_tool(endpoint, source_name="s")
    assert len(result.transactions) == 1
    assert result.transactions[0].reference is None
    assert result.issues == []


def test_api_renamed_required_field_with_map(mock_api):
    endpoint = mock_api([
        {"transaction_id": "A1", "date": "2026-01-01", "amount": "100.00",
         "currency": "USD", "counterparty": "ACME", "reference": "INV-1"},
    ])
    result = api_fetch_tool(endpoint, source_name="s", field_map={"transaction_id": "txn_id"})
    assert len(result.transactions) == 1
    assert result.issues == []


def test_api_renamed_required_field_without_map_is_rejected_not_a_crash(mock_api):
    endpoint = mock_api([
        {"transaction_id": "A1", "date": "2026-01-01", "amount": "100.00",
         "currency": "USD", "counterparty": "ACME"},
    ])
    result = api_fetch_tool(endpoint, source_name="s")  # no field_map
    assert result.transactions == []
    assert len(result.issues) == 1
    assert result.issues[0].severity == "error"


def test_api_required_field_key_entirely_missing_is_rejected_not_a_crash(mock_api):
    endpoint = mock_api([
        {"txn_id": "A1", "date": "2026-01-01", "amount": "100.00", "currency": "USD"},
        # counterparty key entirely missing
    ])
    result = api_fetch_tool(endpoint, source_name="s")
    assert result.transactions == []
    assert len(result.issues) == 1
    assert result.issues[0].severity == "error"


# ---- SFTP: drift matrix (delegates to csv_read_tool internally, so this
# also confirms that delegation doesn't lose or mangle drift handling) ----


def test_sftp_canonical_fields_all_present(tmp_path):
    client = FakeSFTPClient(
        "txn_id,date,amount,currency,counterparty,reference\n"
        "S1,2026-01-01,100.00,USD,ACME,INV-1\n"
    )
    result = sftp_fetch_tool(
        host="h", remote_path="/t.csv", source_name="s",
        local_dir=str(tmp_path), sftp_client=client,
    )
    assert len(result.transactions) == 1
    assert result.issues == []


def test_sftp_optional_reference_column_entirely_absent(tmp_path):
    client = FakeSFTPClient(
        "txn_id,date,amount,currency,counterparty\n"
        "S1,2026-01-01,100.00,USD,ACME\n"
    )
    result = sftp_fetch_tool(
        host="h", remote_path="/t.csv", source_name="s",
        local_dir=str(tmp_path), sftp_client=client,
    )
    assert len(result.transactions) == 1
    assert result.transactions[0].reference is None
    assert result.issues == []


def test_sftp_renamed_required_field_with_map(tmp_path):
    client = FakeSFTPClient(
        "transaction_id,date,amount,currency,counterparty,reference\n"
        "S1,2026-01-01,100.00,USD,ACME,INV-1\n"
    )
    result = sftp_fetch_tool(
        host="h", remote_path="/t.csv", source_name="s",
        local_dir=str(tmp_path), sftp_client=client,
        field_map={"transaction_id": "txn_id"},
    )
    assert len(result.transactions) == 1
    assert result.issues == []


def test_sftp_renamed_required_field_without_map_is_rejected_not_a_crash(tmp_path):
    client = FakeSFTPClient(
        "transaction_id,date,amount,currency,counterparty,reference\n"
        "S1,2026-01-01,100.00,USD,ACME,INV-1\n"
    )
    result = sftp_fetch_tool(
        host="h", remote_path="/t.csv", source_name="s",
        local_dir=str(tmp_path), sftp_client=client,
    )  # no field_map
    assert result.transactions == []
    assert len(result.issues) == 1
    assert result.issues[0].severity == "error"


def test_sftp_required_field_column_entirely_missing_is_rejected_not_a_crash(tmp_path):
    client = FakeSFTPClient(
        "txn_id,date,amount,currency\n"  # counterparty column entirely missing
        "S1,2026-01-01,100.00,USD\n"
    )
    result = sftp_fetch_tool(
        host="h", remote_path="/t.csv", source_name="s",
        local_dir=str(tmp_path), sftp_client=client,
    )
    assert result.transactions == []
    assert len(result.issues) == 1
    assert result.issues[0].severity == "error"


# ---- cross-source-type consistency check ----


def test_all_three_source_types_agree_on_missing_optional_field_behavior(tmp_path, mock_api):
    """The whole point of a drift matrix: not just that each tool individually
    handles a missing optional field, but that CSV/API/SFTP all handle it
    THE SAME WAY (reference -> None, zero issues), since callers building a
    graph on top of these shouldn't have to special-case behavior per source
    type.
    """
    csv_file = tmp_path / "book.csv"
    csv_file.write_text("txn_id,date,amount,currency,counterparty\nX1,2026-01-01,50.00,USD,ACME\n")
    csv_result = csv_read_tool(str(csv_file), source_name="csv")

    endpoint = mock_api([
        {"txn_id": "X1", "date": "2026-01-01", "amount": "50.00", "currency": "USD", "counterparty": "ACME"},
    ])
    api_result = api_fetch_tool(endpoint, source_name="api")

    sftp_client = FakeSFTPClient("txn_id,date,amount,currency,counterparty\nX1,2026-01-01,50.00,USD,ACME\n")
    sftp_result = sftp_fetch_tool(
        host="h", remote_path="/t.csv", source_name="sftp",
        local_dir=str(tmp_path), sftp_client=sftp_client,
    )

    for result in (csv_result, api_result, sftp_result):
        assert len(result.transactions) == 1
        assert result.transactions[0].reference is None
        assert result.issues == []
