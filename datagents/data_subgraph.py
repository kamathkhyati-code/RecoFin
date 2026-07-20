"""Data sub-graph (A10) - compose ingestion -> validation -> normalization.
A standalone, testable unit that threads state through the three data-agent
nodes in order, proving they compose correctly on real state before the real
LangGraph wiring happens at integration (A11).
"""
from __future__ import annotations
from typing import Any
from datagents.agents.ingestion_agent import ingestion_agent
from datagents.agents.normalization_agent import normalization_agent
from datagents.agents.validation_agent import validation_agent
from datagents.schemas import Currency
from datagents.tools.alias_store import AliasStore
from recon_platform.gateway.llm_gateway import LLMGateway
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
