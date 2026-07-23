"""Tests for the CSV source tool (A3)."""
from decimal import Decimal

from datagents.tools.csv_read_tool import csv_read_tool


def test_csv_reads_valid_rows(tmp_path):
    csv_file = tmp_path / "txns.csv"
    csv_file.write_text(
        "txn_id,date,amount,currency,counterparty,reference\n"
        "T1,2026-01-15,100.50,USD,ACME Corp,INV-1\n"
        "T2,2026-01-16,-25.00,EUR,Globex,\n"
    )

    result = csv_read_tool(str(csv_file), source_name="bank")

    assert result.rows_read == 2
    assert len(result.transactions) == 2
    assert result.transactions[0].amount == Decimal("100.50")
    assert result.transactions[1].currency == "EUR"
    assert result.ok is True


def test_csv_flags_bad_row(tmp_path):
    csv_file = tmp_path / "bad.csv"
    csv_file.write_text(
        "txn_id,date,amount,currency,counterparty,reference\n"
        "T1,2026-01-15,100.00,USD,ACME,\n"
        "T2,not-a-date,50.00,USD,Globex,\n"  # bad date
    )

    result = csv_read_tool(str(csv_file), source_name="bank")

    assert result.rows_read == 2
    assert len(result.transactions) == 1  # only the good row parsed
    assert len(result.issues) == 1
    assert result.ok is False  # an error issue exists


def test_csv_missing_file():
    result = csv_read_tool("does_not_exist.csv", source_name="bank")

    assert result.transactions == []
    assert len(result.issues) == 1
    assert result.ok is False
