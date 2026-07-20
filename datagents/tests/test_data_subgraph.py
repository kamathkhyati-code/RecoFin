"""Tests for A10: data sub-graph (ingestion -> validation -> normalization)."""
from __future__ import annotations
from pathlib import Path

from datagents.data_subgraph import run_data_subgraph
from datagents.schemas import Currency, SourceConfig, SourceType

_SAMPLE_DIR = Path(__file__).resolve().parents[2] / "sample_data"


def _golden_configs():
    field_map = {
        "transaction_id": "txn_id",
        "value_date": "date",
        "ccy": "currency",
    }
    return [
        SourceConfig(
            name="book",
            source_type=SourceType.CSV,
            location=str(_SAMPLE_DIR / "book.csv"),
        ),
        SourceConfig(
            name="bank",
            source_type=SourceType.CSV,
            location=str(_SAMPLE_DIR / "bank_source.csv"),
            options={"field_map": field_map},
        ),
    ]


def test_data_subgraph_end_to_end_on_golden_data():
    state = {"source_configs": _golden_configs()}

    result = run_data_subgraph(state)

    # ingestion: 4 book + 3 valid bank = 7 transactions; 2 bad bank rows -> issues
    assert len(result["transactions"]) == 7
    assert len(result["issues"]) >= 2

    # normalization ran and produced one normalized copy per ingested transaction
    assert len(result["normalized_transactions"]) == 7
    assert all(t.currency == Currency.USD for t in result["normalized_transactions"])

    # every txn_id survives normalization unchanged
    original_ids = {t.txn_id for t in result["transactions"]}
    normalized_ids = {t.txn_id for t in result["normalized_transactions"]}
    assert original_ids == normalized_ids


def test_data_subgraph_state_keys_present():
    state = {"source_configs": _golden_configs()}
    result = run_data_subgraph(state)
    assert "validation_findings" in result
    assert "normalized_transactions" in result
    assert "issues" in result
    assert "transactions" in result
