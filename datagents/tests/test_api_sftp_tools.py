"""Tests for API and SFTP source tools (A3)."""
from decimal import Decimal

from datagents.schemas import SourceType
from datagents.tools.api_fetch_tool import api_fetch_tool
from datagents.tools.sftp_fetch_tool import sftp_fetch_tool


def test_api_parses_valid_records():
    records = [
        {"txn_id": "A1", "date": "2026-01-15", "amount": "250.75",
         "currency": "USD", "counterparty": "ACME Corp", "reference": "INV-9"},
        {"txn_id": "A2", "date": "2026-01-16", "amount": -40,
         "currency": "gbp", "counterparty": "Globex"},
    ]

    result = api_fetch_tool(records, source_name="erp")

    assert result.rows_read == 2
    assert len(result.transactions) == 2
    assert result.transactions[0].amount == Decimal("250.75")
    assert result.transactions[1].currency == "GBP"  # normalized
    assert result.transactions[0].source == SourceType.API
    assert result.ok is True


def test_api_flags_bad_record():
    records = [
        {"txn_id": "A1", "date": "2026-01-15", "amount": "10.00",
         "currency": "USD", "counterparty": "ACME"},
        {"txn_id": "A2", "date": "2026-01-16", "amount": "20.00",
         "currency": "TOOLONG", "counterparty": "Globex"},  # bad currency
    ]

    result = api_fetch_tool(records, source_name="erp")

    assert result.rows_read == 2
    assert len(result.transactions) == 1
    assert len(result.issues) == 1
    assert result.ok is False


def test_sftp_reads_and_tags_source(tmp_path):
    remote = tmp_path / "remote.csv"
    remote.write_text(
        "txn_id,date,amount,currency,counterparty,reference\n"
        "S1,2026-01-15,99.99,EUR,Initech,REF-1\n"
    )

    result = sftp_fetch_tool(str(remote), source_name="bank_sftp")

    assert result.rows_read == 1
    assert len(result.transactions) == 1
    assert result.transactions[0].source == SourceType.SFTP  # re-tagged, not CSV
    assert result.ok is True


def test_sftp_missing_file():
    result = sftp_fetch_tool("no_such_remote.csv", source_name="bank_sftp")

    assert result.transactions == []
    assert len(result.issues) == 1
    assert result.ok is False
