"""Validation Agent (A6) — runs deterministic validation tools + LLM fallback.

Runs the four deterministic checks (completeness, dedupe, format, fx) over the
ingested transactions and tags each problem with a ReasonCode. Rows that pass
every check but look ambiguous (no reference) are optionally sent to the LLM
gateway for a verdict. Returns the findings plus IssueRecords for shared state.
"""
from __future__ import annotations

from typing import Any

from datagents.schemas import Transaction
from datagents.tools.validation_tools import (
    ReasonCode,
    ValidationFinding,
    completeness_tool,
    dedupe_tool,
    format_tool,
    fx_check_tool,
)
from recon_platform.gateway.llm_gateway import LLMGateway
from recon_platform.state import IssueRecord

_DETERMINISTIC_TOOLS = (completeness_tool, dedupe_tool, format_tool, fx_check_tool)


def _is_ambiguous(txn: Transaction) -> bool:
    """Passed every deterministic check but has no reference to anchor it."""
    return txn.reference is None


def _ambiguous_prompt(txn: Transaction) -> str:
    return (
        "A financial transaction has no reference/invoice number. "
        "Reply 'ok' if it looks legitimate or 'review' if it needs a human. "
        f"Transaction: id={txn.txn_id}, amount={txn.amount} {txn.currency.value}, "
        f"counterparty={txn.counterparty}, date={txn.date.isoformat()}."
    )


def validate_transactions(
    txns: list[Transaction],
    *,
    gateway: LLMGateway | None = None,
) -> list[ValidationFinding]:
    """Run all deterministic checks; optionally ask the LLM about ambiguous rows."""
    findings: list[ValidationFinding] = []
    for tool in _DETERMINISTIC_TOOLS:
        findings.extend(tool(txns))

    flagged_ids = {f.txn_id for f in findings}
    if gateway is not None:
        for txn in txns:
            if txn.txn_id in flagged_ids:
                continue
            if _is_ambiguous(txn):
                verdict = gateway.generate(_ambiguous_prompt(txn))
                findings.append(
                    ValidationFinding(
                        txn_id=txn.txn_id,
                        reason=ReasonCode.AMBIGUOUS,
                        detail=f"LLM verdict: {verdict}",
                    )
                )
    return findings


def validation_agent(
    state: dict[str, Any],
    *,
    gateway: LLMGateway | None = None,
) -> dict[str, Any]:
    """LangGraph node: validate ingested transactions and record findings."""
    txns = state.get("transactions", [])
    findings = validate_transactions(txns, gateway=gateway)
    issues = []
    for f in findings:
        severity = "warning" if f.reason == ReasonCode.AMBIGUOUS else "error"
        issues.append(
            IssueRecord(
                source="validation",
                severity=severity,
                message=f"{f.reason.value}: {f.detail}",
                row_ref=f.txn_id,
            )
        )
    return {"validation_findings": findings, "issues": issues}
