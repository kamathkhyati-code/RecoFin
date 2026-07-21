"""A13: ingestion observability + metrics.

Covers:
  - ToolSpan captures rows_in/rows_out/issues_out/retry_attempts/duration
    correctly per source.
  - ingestion_agent(state) surfaces these as state["ingestion_metrics"].
  - Regression: a source that never recovers (retries exhausted) used to
    let FetchError propagate and crash the whole ingestion run. It now
    degrades to a recorded error issue instead, same as every other
    source-level failure mode -- discovered while wiring retry-attempt
    capture for this task, not part of the original ask, but a real gap
    once found.
"""
from __future__ import annotations

from datagents.agents.ingestion_agent import (
    ingest_sources_with_metrics,
    ingestion_agent,
)
from datagents.observability import ToolSpan, timed
from datagents.resilience import FetchError
from datagents.schemas import SourceConfig, SourceType

_HEADER = "txn_id,date,amount,currency,counterparty,reference\n"


def test_timed_reports_nonnegative_elapsed_ms():
    with timed() as t:
        pass
    assert t["ms"] >= 0


def test_toolspan_as_dict_round_trips():
    span = ToolSpan(
        source_name="bank", source_type="csv", rows_in=2, rows_out=2,
        issues_out=0, retry_attempts=1, duration_ms=1.5, status="ok",
    )
    d = span.as_dict()
    assert d == {
        "source_name": "bank", "source_type": "csv", "rows_in": 2, "rows_out": 2,
        "issues_out": 0, "retry_attempts": 1, "duration_ms": 1.5, "status": "ok",
    }


def test_metrics_capture_rows_in_out_for_a_clean_source(tmp_path):
    f = tmp_path / "bank.csv"
    f.write_text(_HEADER + "T1,2026-01-01,100.00,USD,ACME,INV-1\n" + "T2,2026-01-02,50.00,EUR,GLOBEX,INV-2\n")
    cfg = SourceConfig(name="bank", source_type=SourceType.CSV, location=str(f))

    merged, spans = ingest_sources_with_metrics([cfg])

    assert len(spans) == 1
    span = spans[0]
    assert span.source_name == "bank"
    assert span.source_type == "csv"
    assert span.rows_in == 2
    assert span.rows_out == 2
    assert span.issues_out == 0
    assert span.retry_attempts == 1
    assert span.status == "ok"
    assert span.duration_ms >= 0
    assert len(merged.transactions) == 2


def test_metrics_capture_retry_attempts_when_source_recovers(tmp_path, monkeypatch):
    calls = {"n": 0}

    def flaky_csv(*args, **kwargs):
        calls["n"] += 1
        if calls["n"] < 3:
            raise FetchError("transient blip")
        from datagents.schemas import IngestResult
        return IngestResult(source_name=kwargs.get("source_name", "csv"))

    monkeypatch.setattr("datagents.agents.ingestion_agent.csv_read_tool", flaky_csv)
    cfg = SourceConfig(
        name="bank", source_type=SourceType.CSV, location="x.csv",
        options={"retry_base_delay": 0},
    )

    merged, spans = ingest_sources_with_metrics([cfg])

    assert spans[0].retry_attempts == 3
    assert spans[0].status == "ok"


def test_source_that_never_recovers_no_longer_crashes_the_run(monkeypatch):
    """Regression: previously a FetchError after exhausted retries propagated
    out of ingest_sources uncaught, crashing the whole ingestion run instead
    of degrading to an error issue like every other failure mode.
    """
    def always_down(*args, **kwargs):
        raise FetchError("source permanently down")

    monkeypatch.setattr("datagents.agents.ingestion_agent.csv_read_tool", always_down)
    cfg = SourceConfig(
        name="bank", source_type=SourceType.CSV, location="x.csv",
        options={"retries": 3, "retry_base_delay": 0},
    )

    merged, spans = ingest_sources_with_metrics([cfg])  # must not raise

    assert merged.transactions == []
    assert len(merged.issues) == 1
    assert merged.issues[0].severity == "error"
    assert spans[0].status == "error"
    assert spans[0].retry_attempts == 3


def test_ingestion_agent_surfaces_metrics_on_state(tmp_path):
    f = tmp_path / "bank.csv"
    f.write_text(_HEADER + "T1,2026-01-01,100.00,USD,ACME,INV-1\n")
    state = {
        "source_configs": [
            SourceConfig(name="bank", source_type=SourceType.CSV, location=str(f)),
        ]
    }

    update = ingestion_agent(state)

    assert "ingestion_metrics" in update
    assert len(update["ingestion_metrics"]) == 1
    assert update["ingestion_metrics"][0]["source_name"] == "bank"
    assert update["ingestion_metrics"][0]["rows_out"] == 1


def test_ingestion_node_itself_returns_metrics_for_book_and_bank(tmp_path):
    """Proves ingestion_node's own return value carries ingestion_metrics
    correctly for both book and bank sources.

    Deliberately calls ingestion_node directly rather than through
    build_graph().invoke(): LangGraph's StateGraph(ReconState) only tracks
    keys declared in the ReconState TypedDict schema and silently drops
    anything else a node returns (confirmed empirically -- an undeclared
    key never reaches the final state, even though the node returned it).
    ReconState doesn't declare "ingestion_metrics" yet, so a full graph.invoke()
    test would currently fail to see this key downstream even though
    ingestion_node is producing it correctly. That's a one-line addition to
    recon_platform/state.py (Khyati's file, same one she extended for A9/A10's
    transactions/source_configs) -- not something to change unilaterally here.
    """
    from recon_platform.graph.build import ingestion_node

    book = tmp_path / "book.csv"
    book.write_text(_HEADER + "B1,2026-01-01,100.00,USD,ACME,INV-1\n")
    bank = tmp_path / "bank.csv"
    bank.write_text(_HEADER + "S1,2026-01-01,100.00,USD,ACME,INV-1\n")

    state = {
        "run_id": "a13-metrics-test",
        "issues": [],
        "book_source_configs": [
            SourceConfig(name="book", source_type=SourceType.CSV, location=str(book)),
        ],
        "bank_source_configs": [
            SourceConfig(name="bank", source_type=SourceType.CSV, location=str(bank)),
        ],
    }

    update = ingestion_node(state)

    assert "ingestion_metrics" in update
    sources = {m["source_name"] for m in update["ingestion_metrics"]}
    assert sources == {"book", "bank"}
    for m in update["ingestion_metrics"]:
        assert m["rows_out"] == 1
        assert m["retry_attempts"] == 1
        assert m["status"] == "ok"
