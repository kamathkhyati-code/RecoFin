"""Tests for the A4 Ingestion Agent node and its multi-source merge."""
from __future__ import annotations

from datagents.agents.ingestion_agent import ingest_sources, ingestion_agent
from datagents.schemas import IngestResult, SourceConfig, SourceType, Transaction

_CANONICAL_HEADER = "txn_id,date,amount,currency,counterparty,reference\n"
_DRIFTED_HEADER = "transaction_id,date,amount,currency,counterparty,reference\n"


def test_ingests_two_sources_and_handles_drift(tmp_path):
    src1 = tmp_path / "bank.csv"
    src1.write_text(
        _CANONICAL_HEADER + "T1,2026-01-01,100.00,USD,ACME,INV-1\n",
        encoding="utf-8",
    )
    src2 = tmp_path / "erp.csv"
    src2.write_text(
        _DRIFTED_HEADER + "T2,2026-01-02,200.00,EUR,GLOBEX,INV-2\n",
        encoding="utf-8",
    )
    configs = [
        SourceConfig(name="bank", source_type=SourceType.CSV, location=str(src1)),
        SourceConfig(
            name="erp",
            source_type=SourceType.CSV,
            location=str(src2),
            options={"field_map": {"transaction_id": "txn_id"}},
        ),
    ]

    merged = ingest_sources(configs)

    assert len(merged.transactions) == 2
    assert all(isinstance(t, Transaction) for t in merged.transactions)
    assert not merged.issues
    assert {t.txn_id for t in merged.transactions} == {"T1", "T2"}


def test_drift_without_field_map_is_rejected(tmp_path):
    src = tmp_path / "erp.csv"
    src.write_text(
        _DRIFTED_HEADER + "T2,2026-01-02,200.00,EUR,GLOBEX,INV-2\n",
        encoding="utf-8",
    )
    configs = [
        SourceConfig(name="erp", source_type=SourceType.CSV, location=str(src)),
    ]

    merged = ingest_sources(configs)

    assert merged.transactions == []
    assert merged.issues


def test_dispatch_selects_tool_by_source_type(monkeypatch):
    called = {}

    def fake_csv(*args, **kwargs):
        called["tool"] = "csv"
        return IngestResult(source_name=kwargs.get("source_name", "csv"))

    monkeypatch.setattr("datagents.agents.ingestion_agent.csv_read_tool", fake_csv)
    cfg = SourceConfig(name="x", source_type=SourceType.CSV, location="whatever.csv")

    ingest_sources([cfg])

    assert called["tool"] == "csv"


def test_ingestion_agent_node_returns_state_update(tmp_path):
    src = tmp_path / "bank.csv"
    src.write_text(
        _CANONICAL_HEADER + "T1,2026-01-01,100.00,USD,ACME,INV-1\n",
        encoding="utf-8",
    )
    state = {
        "source_configs": [
            SourceConfig(name="bank", source_type=SourceType.CSV, location=str(src)),
        ]
    }

    update = ingestion_agent(state)

    assert len(update["transactions"]) == 1
    assert isinstance(update["transactions"][0], Transaction)
