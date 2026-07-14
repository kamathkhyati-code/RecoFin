"""Ingestion Agent (A4/A5) — LangGraph node: run source tools, retry, merge.

Picks the right source tool per SourceConfig.source_type, applies schema-drift
handling via each config's `field_map`, retries transient fetch failures with
backoff, merges the per-source IngestResults into one typed dataset, and emits a
structured log line per source and for the overall run.
"""
from __future__ import annotations

import logging
from typing import Any

from datagents.resilience import with_retry
from datagents.schemas import IngestResult, SourceConfig, SourceType
from datagents.tools.api_fetch_tool import api_fetch_tool
from datagents.tools.csv_read_tool import csv_read_tool
from datagents.tools.sftp_fetch_tool import sftp_fetch_tool

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


def _run_source(config: SourceConfig) -> IngestResult:
    """Run one source with transient-failure retry, then log the outcome."""
    options = config.options or {}
    result = with_retry(
        lambda: _call_tool(config),
        retries=options.get("retries", 3),
        base_delay=options.get("retry_base_delay", 0.5),
    )
    logger.info(
        "source_ingested",
        extra={
            "source": config.name,
            "type": config.source_type.value,
            "rows_read": result.rows_read,
            "transactions": len(result.transactions),
            "issues": len(result.issues),
        },
    )
    return result


def ingest_sources(configs: list[SourceConfig]) -> IngestResult:
    """Run every source (with retry) and merge results into one IngestResult."""
    merged = IngestResult(source_name="merged")
    for config in configs:
        result = _run_source(config)
        merged.transactions.extend(result.transactions)
        merged.issues.extend(result.issues)
        merged.rows_read += result.rows_read
    return merged


def ingestion_agent(state: dict[str, Any]) -> dict[str, Any]:
    """LangGraph node: ingest all configured sources into merged state."""
    configs = state.get("source_configs", [])
    merged = ingest_sources(configs)
    logger.info(
        "ingestion_complete",
        extra={
            "sources": len(configs),
            "transactions": len(merged.transactions),
            "issues": len(merged.issues),
        },
    )
    return {"transactions": merged.transactions, "issues": merged.issues}
