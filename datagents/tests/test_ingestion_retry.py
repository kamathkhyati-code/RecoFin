"""Test that the ingestion agent retries a source that fails transiently."""
from __future__ import annotations

from datetime import date
from decimal import Decimal

from datagents.agents.ingestion_agent import ingest_sources
from datagents.resilience import FetchError
from datagents.schemas import IngestResult, SourceConfig, SourceType, Transaction


def test_agent_retries_transient_source_then_succeeds(monkeypatch):
    calls = {"n": 0}

    def flaky_csv(*args, **kwargs):
        calls["n"] += 1
        if calls["n"] < 3:
            raise FetchError("transient blip")
        result = IngestResult(source_name=kwargs.get("source_name", "csv"))
        result.transactions.append(
            Transaction(
                txn_id="T1",
                date=date(2026, 1, 1),
                amount=Decimal("100.00"),
                currency="USD",
                counterparty="ACME",
                source=SourceType.CSV,
            )
        )
        return result

    monkeypatch.setattr("datagents.agents.ingestion_agent.csv_read_tool", flaky_csv)
    cfg = SourceConfig(
        name="bank",
        source_type=SourceType.CSV,
        location="x.csv",
        options={"retry_base_delay": 0},
    )

    merged = ingest_sources([cfg])

    assert calls["n"] == 3
    assert len(merged.transactions) == 1
    assert merged.transactions[0].txn_id == "T1"
