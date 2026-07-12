"""Ingestion Agent (A4) — LangGraph node that runs source tools and merges output.

Picks the right source tool per SourceConfig.source_type, applies schema-drift
handling via each config's `field_map` (in SourceConfig.options), runs every
source, and merges the per-source IngestResults into one typed dataset.
"""
from __future__ import annotations

from typing import Any

from datagents.schemas import IngestResult, SourceConfig, SourceType
from datagents.tools.api_fetch_tool import api_fetch_tool
from datagents.tools.csv_read_tool import csv_read_tool
from datagents.tools.sftp_fetch_tool import sftp_fetch_tool


def _run_source(config: SourceConfig) -> IngestResult:
    """Dispatch a single SourceConfig to its source tool and return the result."""
    options = config.options or {}
    field_map = options.get("field_map")

    if config.source_type == SourceType.CSV:
        return csv_read_tool(
            config.location,
            source_name=config.name,
            field_map=field_map,
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


def ingest_sources(configs: list[SourceConfig]) -> IngestResult:
    """Run every source and merge results into one IngestResult.

    Transactions and issues are concatenated across sources; rows_read is summed.
    A failing source does not abort the others -- its failure lands in `issues`.
    """
    merged = IngestResult(source_name="merged")
    for config in configs:
        result = _run_source(config)
        merged.transactions.extend(result.transactions)
        merged.issues.extend(result.issues)
        merged.rows_read += result.rows_read
    return merged


def ingestion_agent(state: dict[str, Any]) -> dict[str, Any]:
    """LangGraph node: ingest all configured sources into merged state.

    Reads `source_configs` from state, ingests them, and returns a state update
    carrying the merged transactions and issues. Kept dict-typed until C adds
    `source_configs` / `transactions` to ReconState (coordination in flight).
    """
    configs = state.get("source_configs", [])
    merged = ingest_sources(configs)
    return {
        "transactions": merged.transactions,
        "issues": merged.issues,
    }
