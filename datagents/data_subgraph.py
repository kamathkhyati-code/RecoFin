"""Data sub-graph (A10) - compose ingestion -> validation -> normalization.
A standalone, testable unit that threads state through the three data-agent
nodes in order, proving they compose correctly on real state before the real
LangGraph wiring happens at integration (A11).

run_data_subgraph: single combined source list -> one merged, normalized
dataset. Matches A10's original spec exactly.

run_data_subgraph_by_source: multiple NAMED source lists (e.g. "book" vs
"source") -> validation still runs across everything combined (so
cross-source checks like dedupe still work), but normalized output stays
split per name, e.g. result["book_transactions"], result["source_transactions"].
This is what matching needs downstream, and what the demo already does
manually by calling ingestion twice - this makes that pattern reusable
instead of hand-rolled in every caller.
"""
from __future__ import annotations
from typing import Any
from datagents.agents.ingestion_agent import ingestion_agent
from datagents.agents.normalization_agent import normalization_agent
from datagents.agents.validation_agent import validation_agent
from datagents.schemas import Currency, SourceConfig, Transaction
from datagents.tools.alias_store import AliasStore
from recon_platform.gateway.llm_gateway import LLMGateway
from recon_platform.state import IssueRecord
def run_data_subgraph(
    state: dict[str, Any],
    *,
    base: Currency = Currency.USD,
    gateway: LLMGateway | None = None,
    store: AliasStore | None = None,
) -> dict[str, Any]:
    """Run ingestion -> validation -> normalization in sequence on `state`.
    Returns the merged state: transactions, issues (ingestion + validation),
    validation_findings, and normalized_transactions.
    """
    working: dict[str, Any] = dict(state)

    ingest_out = ingestion_agent(working)
    working["transactions"] = ingest_out["transactions"]
    working["issues"] = list(ingest_out["issues"])

    validate_out = validation_agent(working, gateway=gateway)
    working["validation_findings"] = validate_out["validation_findings"]
    working["issues"] = working["issues"] + validate_out["issues"]

    normalize_out = normalization_agent(
        working, base=base, gateway=gateway, store=store
    )
    working["normalized_transactions"] = normalize_out["normalized_transactions"]

    return working
def run_data_subgraph_by_source(
    named_configs: dict[str, list[SourceConfig]],
    *,
    base: Currency = Currency.USD,
    gateway: LLMGateway | None = None,
    store: AliasStore | None = None,
) -> dict[str, Any]:
    """Same pipeline as run_data_subgraph, but keeps each named source's
    transactions separate through normalization, so callers (like matching)
    can tell book apart from bank. Validation still sees everything combined,
    since cross-source checks (e.g. dedupe) need the full picture.
    """
    per_name_raw: dict[str, list[Transaction]] = {}
    all_transactions: list[Transaction] = []
    all_issues: list[IssueRecord] = []

    for name, configs in named_configs.items():
        ingest_out = ingestion_agent({"source_configs": configs})
        per_name_raw[name] = ingest_out["transactions"]
        all_transactions.extend(ingest_out["transactions"])
        all_issues.extend(ingest_out["issues"])

    validate_out = validation_agent({"transactions": all_transactions}, gateway=gateway)
    all_issues = all_issues + validate_out["issues"]

    result: dict[str, Any] = {
        "transactions": all_transactions,
        "issues": all_issues,
        "validation_findings": validate_out["validation_findings"],
    }
    for name, txns in per_name_raw.items():
        normalize_out = normalization_agent(
            {"transactions": txns}, base=base, gateway=gateway, store=store
        )
        result[f"{name}_transactions"] = normalize_out["normalized_transactions"]

    return result
