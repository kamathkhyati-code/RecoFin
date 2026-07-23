"""Ingestion Agent (A4/A5) — LangGraph node: run source tools, retry, merge.

Picks the right source tool per SourceConfig.source_type, applies schema-drift
handling via each config's `field_map`, retries transient fetch failures with
backoff, merges the per-source IngestResults into one typed dataset, and emits a
structured log line per source and for the overall run.

A13: also records a ToolSpan per source (rows in/out, retry attempts,
duration, status) and surfaces the list as state["ingestion_metrics"]. As
part of this, _run_source now catches FetchError once retries are
exhausted instead of letting it propagate -- previously an unrecoverable
source would crash the whole ingestion run rather than degrading to a
recorded issue like every other failure mode (bad file, bad row, dead API)
already does. That gap only became visible while wiring retry-attempt
capture here; test_ingestion_observability.py covers it as a regression.
"""
from __future__ import annotations

import logging
from typing import Any

from datagents.observability import ToolSpan, timed
from datagents.resilience import FetchError, with_retry
from datagents.schemas import IngestResult, SourceConfig, SourceType
from datagents.tools.api_fetch_tool import api_fetch_tool
from datagents.tools.csv_read_tool import csv_read_tool
from datagents.tools.sftp_fetch_tool import sftp_fetch_tool
from recon_platform.state import IssueRecord

logger = logging.getLogger("datagents.ingestion.agent")


def _call_tool(config: SourceConfig) -> IngestResult:
    """Dispatch a single SourceConfig to its source tool (no retry)."""
    options = config.options or {}
    field_map = options.get("field_map")

    if config.source_type == SourceType.CSV:
        return csv_read_tool(
            config.location, source_name=config.name, field_map=field_map
        )
    if config.source_type == SourceType.API:
        return api_fetch_tool(
            config.location,
            source_name=config.name,
            timeout=options.get("timeout", 5.0),
            field_map=field_map,
        )
    if config.source_type == SourceType.SFTP:
        return sftp_fetch_tool(
            host=options.get("host", ""),
            remote_path=config.location,
            source_name=config.name,
            username=options.get("username", ""),
            password=options.get("password", ""),
            port=options.get("port", 22),
            local_dir=options.get("local_dir", ".sftp_staging"),
            sftp_client=options.get("sftp_client"),
            field_map=field_map,
        )
    raise ValueError(f"Unsupported source_type: {config.source_type!r}")


def _run_source(config: SourceConfig) -> tuple[IngestResult, ToolSpan]:
    """Run one source with transient-failure retry, log the outcome, and
    return both the IngestResult and a ToolSpan recording rows/retries/timing.

    If retries are exhausted, this no longer lets FetchError propagate: it
    degrades to an IngestResult carrying a single error issue (row_ref=None,
    i.e. a genuinely batch-level/critical issue per validation_gate), same
    as every other source-level failure mode.
    """
    options = config.options or {}
    attempts: list[int] = []
    status = "ok"

    with timed() as timer:
        try:
            result = with_retry(
                lambda: _call_tool(config),
                retries=options.get("retries", 3),
                base_delay=options.get("retry_base_delay", 0.5),
                attempts_out=attempts,
            )
        except FetchError as exc:
            status = "error"
            result = IngestResult(source_name=config.name)
            result.issues.append(
                IssueRecord(
                    source=config.name,
                    severity="error",
                    message=f"Source unreachable after {attempts[-1] if attempts else 0} attempt(s): {exc}",
                )
            )

    span = ToolSpan(
        source_name=config.name,
        source_type=config.source_type.value,
        rows_in=result.rows_read,
        rows_out=len(result.transactions),
        issues_out=len(result.issues),
        retry_attempts=attempts[-1] if attempts else 1,
        duration_ms=timer["ms"],
        status=status,
    )

    logger.info(
        "source_ingested",
        extra={
            "source": config.name,
            "type": config.source_type.value,
            "rows_read": result.rows_read,
            "transactions": len(result.transactions),
            "issues": len(result.issues),
            "retry_attempts": span.retry_attempts,
            "duration_ms": span.duration_ms,
            "status": status,
        },
    )
    return result, span


def ingest_sources(configs: list[SourceConfig]) -> IngestResult:
    """Run every source (with retry) and merge results into one IngestResult.

    Metrics (ToolSpan per source) are discarded here -- this function's
    contract predates A13 and stays a plain IngestResult for existing
    callers. Use ingestion_agent() for the metrics-carrying state update.
    """
    merged = IngestResult(source_name="merged")
    for config in configs:
        result, _span = _run_source(config)
        merged.transactions.extend(result.transactions)
        merged.issues.extend(result.issues)
        merged.rows_read += result.rows_read
    return merged


def ingest_sources_with_metrics(
    configs: list[SourceConfig],
) -> tuple[IngestResult, list[ToolSpan]]:
    """Same as ingest_sources, but also returns a ToolSpan per source."""
    merged = IngestResult(source_name="merged")
    spans: list[ToolSpan] = []
    for config in configs:
        result, span = _run_source(config)
        merged.transactions.extend(result.transactions)
        merged.issues.extend(result.issues)
        merged.rows_read += result.rows_read
        spans.append(span)
    return merged, spans


def ingestion_agent(state: dict[str, Any]) -> dict[str, Any]:
    """LangGraph node: ingest all configured sources into merged state."""
    configs = state.get("source_configs", [])
    merged, spans = ingest_sources_with_metrics(configs)
    logger.info(
        "ingestion_complete",
        extra={
            "sources": len(configs),
            "transactions": len(merged.transactions),
            "issues": len(merged.issues),
        },
    )
    return {
        "transactions": merged.transactions,
        "issues": merged.issues,
        "ingestion_metrics": [s.as_dict() for s in spans],
    }
