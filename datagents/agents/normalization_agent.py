"""Normalization Agent (A8) — apply the normalization tools to a batch.

Takes validated transactions and returns normalized copies: amounts converted
to a base currency, counterparties resolved to canonical names, and references
put in canonical form. The output is ready for the matching step.
"""
from __future__ import annotations

from typing import Any

from datagents.schemas import Currency, Transaction
from datagents.tools.normalization_tools import (
    canonicalize_reference,
    entity_alias_tool,
    fx_rate_tool,
)
from recon_platform.gateway.llm_gateway import LLMGateway


def normalize_transactions(
    txns: list[Transaction],
    *,
    base: Currency = Currency.USD,
    gateway: LLMGateway | None = None,
) -> list[Transaction]:
    """Return normalized copies of each transaction, ready for matching."""
    normalized: list[Transaction] = []
    for t in txns:
        normalized.append(
            t.model_copy(
                update={
                    "amount": fx_rate_tool(t.amount, t.currency, base),
                    "currency": base,
                    "counterparty": entity_alias_tool(t.counterparty, gateway),
                    "reference": canonicalize_reference(t.reference),
                }
            )
        )
    return normalized


def normalization_agent(
    state: dict[str, Any],
    *,
    base: Currency = Currency.USD,
    gateway: LLMGateway | None = None,
) -> dict[str, Any]:
    """LangGraph node: normalize the transactions in state for matching."""
    txns = state.get("transactions", [])
    normalized = normalize_transactions(txns, base=base, gateway=gateway)
    return {"normalized_transactions": normalized}
