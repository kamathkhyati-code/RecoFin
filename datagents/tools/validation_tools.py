"""Validation tools (A6) — deterministic checks that flag bad transactions.

Each tool takes the batch of transactions and returns a list of findings, one
per problem, tagged with a machine-readable ReasonCode. A7 adds the LLMVerdict
schema and an `escalate` flag used by the guardrailed AI fallback.
"""
from __future__ import annotations

from enum import Enum
from typing import Literal

from pydantic import BaseModel, Field

from datagents.schemas import Currency, Transaction
from recon_platform.registry import registry

# Currencies we can actually reconcile / FX-convert in the POC.
SUPPORTED_CURRENCIES = {Currency.USD, Currency.EUR, Currency.GBP}


class ReasonCode(str, Enum):
    """Machine-readable code explaining why a transaction was flagged."""

    MISSING_FIELD = "MISSING_FIELD"
    DUPLICATE_TXN = "DUPLICATE_TXN"
    NON_POSITIVE_AMOUNT = "NON_POSITIVE_AMOUNT"
    UNSUPPORTED_CURRENCY = "UNSUPPORTED_CURRENCY"
    AMBIGUOUS = "AMBIGUOUS"


class ValidationFinding(BaseModel):
    """One problem found on one transaction."""

    txn_id: str
    reason: ReasonCode
    detail: str
    escalate: bool = False


class LLMVerdict(BaseModel):
    """Strict shape the LLM must return for an ambiguous-row judgment."""

    verdict: Literal["ok", "review"]
    confidence: float = Field(ge=0.0, le=1.0)
    reason: str


@registry.register(
    "completeness_tool",
    description="Flag transactions with a blank required field.",
)
def completeness_tool(txns: list[Transaction]) -> list[ValidationFinding]:
    findings: list[ValidationFinding] = []
    for t in txns:
        if not t.txn_id.strip() or not t.counterparty.strip():
            findings.append(
                ValidationFinding(
                    txn_id=t.txn_id,
                    reason=ReasonCode.MISSING_FIELD,
                    detail="blank txn_id or counterparty",
                )
            )
    return findings


@registry.register(
    "dedupe_tool",
    description="Flag transactions whose txn_id appears more than once.",
)
def dedupe_tool(txns: list[Transaction]) -> list[ValidationFinding]:
    findings: list[ValidationFinding] = []
    seen: set[str] = set()
    for t in txns:
        if t.txn_id in seen:
            findings.append(
                ValidationFinding(
                    txn_id=t.txn_id,
                    reason=ReasonCode.DUPLICATE_TXN,
                    detail=f"duplicate txn_id {t.txn_id}",
                )
            )
        seen.add(t.txn_id)
    return findings


@registry.register(
    "format_tool",
    description="Flag transactions with a non-positive amount.",
)
def format_tool(txns: list[Transaction]) -> list[ValidationFinding]:
    findings: list[ValidationFinding] = []
    for t in txns:
        if t.amount <= 0:
            findings.append(
                ValidationFinding(
                    txn_id=t.txn_id,
                    reason=ReasonCode.NON_POSITIVE_AMOUNT,
                    detail=f"amount {t.amount} is not positive",
                )
            )
    return findings


@registry.register(
    "fx_check_tool",
    description="Flag transactions in a currency we cannot reconcile.",
)
def fx_check_tool(txns: list[Transaction]) -> list[ValidationFinding]:
    findings: list[ValidationFinding] = []
    for t in txns:
        if t.currency not in SUPPORTED_CURRENCIES:
            findings.append(
                ValidationFinding(
                    txn_id=t.txn_id,
                    reason=ReasonCode.UNSUPPORTED_CURRENCY,
                    detail=f"currency {t.currency.value} not supported for FX",
                )
            )
    return findings
