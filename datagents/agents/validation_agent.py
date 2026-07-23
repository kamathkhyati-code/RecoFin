"""Validation Agent (A6/A7) — deterministic checks + guardrailed LLM fallback.

Runs the four deterministic checks over the ingested transactions and tags each
problem with a ReasonCode. Rows that pass every check but look ambiguous (no
reference) are sent to the LLM, whose answer is forced into the LLMVerdict shape
by C's validate_with_retry guard. A "review" verdict, low confidence, or an
unusable answer sets the escalate flag so a human takes a look.
"""
from __future__ import annotations

from typing import Any

from datagents.schemas import Transaction
from datagents.tools.validation_tools import (
    LLMVerdict,
    ReasonCode,
    ValidationFinding,
    completeness_tool,
    dedupe_tool,
    format_tool,
    fx_check_tool,
)
from recon_platform.gateway.llm_gateway import LLMGateway
from recon_platform.guardrails.validators import GuardrailError, validate_with_retry
from recon_platform.state import IssueRecord

_DETERMINISTIC_TOOLS = (completeness_tool, dedupe_tool, format_tool, fx_check_tool)

# Below this confidence we send the row to a human even if the LLM said "ok".
ESCALATE_CONFIDENCE = 0.7


def _is_ambiguous(txn: Transaction) -> bool:
    """Passed every deterministic check but has no reference to anchor it."""
    return txn.reference is None


def _ambiguous_prompt(txn: Transaction) -> str:
    return (
        "A financial transaction has no reference/invoice number. Decide whether "
        "it is fine or needs human review. Reply ONLY as JSON with keys "
        '"verdict" ("ok" or "review"), "confidence" (0.0-1.0), and "reason". '
        f"Transaction: id={txn.txn_id}, amount={txn.amount} {txn.currency.value}, "
        f"counterparty={txn.counterparty}, date={txn.date.isoformat()}."
    )


def _judge_ambiguous(txn: Transaction, gateway: LLMGateway) -> ValidationFinding:
    """Ask the LLM for a verdict, guarded into the LLMVerdict shape."""
    try:
        verdict = validate_with_retry(
            LLMVerdict, lambda: gateway.generate(_ambiguous_prompt(txn))
        )
    except GuardrailError as exc:
        # The LLM never produced a usable answer -> escalate, don't guess.
        return ValidationFinding(
            txn_id=txn.txn_id,
            reason=ReasonCode.AMBIGUOUS,
            detail=f"LLM output unusable: {exc}",
            escalate=True,
        )
    escalate = verdict.verdict == "review" or verdict.confidence < ESCALATE_CONFIDENCE
    return ValidationFinding(
        txn_id=txn.txn_id,
        reason=ReasonCode.AMBIGUOUS,
        detail=f"verdict={verdict.verdict} confidence={verdict.confidence}: {verdict.reason}",
        escalate=escalate,
    )


def validate_transactions(
    txns: list[Transaction],
    *,
    gateway: LLMGateway | None = None,
) -> list[ValidationFinding]:
    """Run all deterministic checks; guardrailed LLM judges ambiguous rows."""
    findings: list[ValidationFinding] = []
    for tool in _DETERMINISTIC_TOOLS:
        findings.extend(tool(txns))

    flagged_ids = {f.txn_id for f in findings}
    if gateway is not None:
        for txn in txns:
            if txn.txn_id not in flagged_ids and _is_ambiguous(txn):
                findings.append(_judge_ambiguous(txn, gateway))
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
