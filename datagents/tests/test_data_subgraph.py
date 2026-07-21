"""Tests for A10: data sub-graph (ingestion -> validation -> normalization)."""
from __future__ import annotations
from pathlib import Path

from datagents.data_subgraph import run_data_subgraph, run_data_subgraph_by_source
from datagents.schemas import Currency, SourceConfig, SourceType

_SAMPLE_DIR = Path(__file__).resolve().parents[2] / "sample_data"
_FIELD_MAP = {
    "transaction_id": "txn_id",
    "value_date": "date",
    "ccy": "currency",
}


def _golden_configs():
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
            options={"field_map": _FIELD_MAP},
        ),
    ]


def test_data_subgraph_end_to_end_on_golden_data():
    state = {"source_configs": _golden_configs()}

    result = run_data_subgraph(state)

    assert len(result["transactions"]) == 7
    assert len(result["issues"]) >= 2
    assert len(result["normalized_transactions"]) == 7
    assert all(t.currency == Currency.USD for t in result["normalized_transactions"])

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


def test_data_subgraph_by_source_keeps_book_and_bank_separate():
    named_configs = {
        "book": [
            SourceConfig(
                name="book",
                source_type=SourceType.CSV,
                location=str(_SAMPLE_DIR / "book.csv"),
            ),
        ],
        "source": [
            SourceConfig(
                name="bank",
                source_type=SourceType.CSV,
                location=str(_SAMPLE_DIR / "bank_source.csv"),
                options={"field_map": _FIELD_MAP},
            ),
        ],
    }

    result = run_data_subgraph_by_source(named_configs)

    assert len(result["book_transactions"]) == 4
    assert len(result["source_transactions"]) == 3
    book_ids = {t.txn_id for t in result["book_transactions"]}
    source_ids = {t.txn_id for t in result["source_transactions"]}
    assert book_ids == {"B1", "B2", "B3", "B4"}
    assert source_ids == {"S1", "S2", "S3"}
    # combined view still present for observability
    assert len(result["transactions"]) == 7
