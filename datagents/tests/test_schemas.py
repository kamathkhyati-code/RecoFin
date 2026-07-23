"""Tests for datagents core schemas (A2)."""
from datetime import date
from decimal import Decimal

import pytest
from pydantic import ValidationError

from datagents.schemas import IngestResult, SourceConfig, SourceType, Transaction


def _valid_txn() -> Transaction:
    return Transaction(
        txn_id="T1",
        date=date(2026, 1, 15),
        amount=Decimal("100.50"),
        currency="usd",
        counterparty="ACME Corp",
        source=SourceType.CSV,
    )


def test_transaction_valid():
    txn = _valid_txn()
    assert txn.amount == Decimal("100.50")
    assert txn.currency == "USD"  # normalized to upper


def test_amount_coerced_from_string():
    txn = Transaction(
        txn_id="T2", date=date(2026, 1, 1), amount="42.00",
        currency="EUR", counterparty="X", source=SourceType.API,
    )
    assert txn.amount == Decimal("42.00")


def test_bad_currency_rejected():
    with pytest.raises(ValidationError):
        Transaction(
            txn_id="T3", date=date(2026, 1, 1), amount=Decimal("1"),
            currency="US", counterparty="X", source=SourceType.CSV,
        )


def test_sourceconfig_defaults():
    cfg = SourceConfig(name="bank", source_type=SourceType.CSV, location="/tmp/x.csv")
    assert cfg.credentials_ref is None
    assert cfg.options == {}


def test_ingestresult_ok_property():
    result = IngestResult(source_name="bank", transactions=[_valid_txn()], rows_read=1)
    assert result.ok is True
