"""Golden-data tests (A5): the sample_data/ files load and validate."""
from __future__ import annotations

from pathlib import Path

from datagents.agents.ingestion_agent import ingest_sources
from datagents.schemas import Currency, SourceConfig, SourceType, Transaction

_SAMPLE_DIR = Path(__file__).resolve().parents[2] / "sample_data"


def test_book_golden_loads_and_validates():
    cfg = SourceConfig(
        name="book",
        source_type=SourceType.CSV,
        location=str(_SAMPLE_DIR / "book.csv"),
    )

    merged = ingest_sources([cfg])

    assert len(merged.transactions) == 4
    assert not merged.issues
    assert all(isinstance(t, Transaction) for t in merged.transactions)
    # lowercase "gbp" in the file was normalized to the GBP enum
    b3 = next(t for t in merged.transactions if t.txn_id == "B3")
    assert b3.currency == Currency.GBP


def test_bank_source_golden_handles_drift_and_bad_rows():
    field_map = {
        "transaction_id": "txn_id",
        "value_date": "date",
        "ccy": "currency",
    }
    cfg = SourceConfig(
        name="bank",
        source_type=SourceType.CSV,
        location=str(_SAMPLE_DIR / "bank_source.csv"),
        options={"field_map": field_map},
    )

    merged = ingest_sources([cfg])

    # S1-S3 are valid; S4 (bad amount) and S5 (fake currency) become issues.
    assert len(merged.transactions) == 3
    assert len(merged.issues) == 2
    assert {t.txn_id for t in merged.transactions} == {"S1", "S2", "S3"}
