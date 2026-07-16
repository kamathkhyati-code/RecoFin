"""Tests for the A6/A7 Validation Agent, checks, and guardrailed LLM verdict."""
from __future__ import annotations

from datetime import date
from decimal import Decimal

from datagents.agents.validation_agent import validate_transactions, validation_agent
from datagents.schemas import SourceType, Transaction
from datagents.tools.validation_tools import ReasonCode
from recon_platform.gateway.llm_gateway import MockLLMGateway


def _txn(
    txn_id="T1",
    amount="100.00",
    currency="USD",
    counterparty="ACME",
    reference="INV-1",
):
    return Transaction(
        txn_id=txn_id,
        date=date(2026, 1, 1),
        amount=Decimal(amount),
        currency=currency,
        counterparty=counterparty,
        reference=reference,
        source=SourceType.CSV,
    )


def test_deterministic_bad_rows_get_correct_reason_codes():
    txns = [
        _txn(txn_id="OK1"),  # clean - must NOT be flagged
        _txn(txn_id="MISS", counterparty=""),  # MISSING_FIELD
        _txn(txn_id="DUP"),  # first occurrence
        _txn(txn_id="DUP"),  # DUPLICATE_TXN on the second
        _txn(txn_id="ZERO", amount="0"),  # NON_POSITIVE_AMOUNT
        _txn(txn_id="FX", currency="JPY"),  # UNSUPPORTED_CURRENCY
    ]

    findings = validate_transactions(txns)

    reasons_by_id: dict[str, set] = {}
    for f in findings:
        reasons_by_id.setdefault(f.txn_id, set()).add(f.reason)

    assert reasons_by_id.get("MISS") == {ReasonCode.MISSING_FIELD}
    assert reasons_by_id.get("DUP") == {ReasonCode.DUPLICATE_TXN}
    assert reasons_by_id.get("ZERO") == {ReasonCode.NON_POSITIVE_AMOUNT}
    assert reasons_by_id.get("FX") == {ReasonCode.UNSUPPORTED_CURRENCY}
    assert "OK1" not in reasons_by_id


def test_ambiguous_row_ignored_without_gateway():
    txns = [_txn(txn_id="NOREF", reference=None)]

    findings = validate_transactions(txns)

    assert findings == []


def test_malformed_llm_verdict_is_caught_and_escalates():
    # The LLM returns junk that doesn't fit LLMVerdict -> guard catches it ->
    # we escalate to a human instead of guessing.
    txns = [_txn(txn_id="NOREF", reference=None)]
    gateway = MockLLMGateway(canned_response="totally not json")

    findings = validate_transactions(txns, gateway=gateway)

    assert len(findings) == 1
    assert findings[0].reason == ReasonCode.AMBIGUOUS
    assert findings[0].escalate is True


def test_review_verdict_sets_escalation():
    txns = [_txn(txn_id="NOREF", reference=None)]
    gateway = MockLLMGateway(
        canned_response='{"verdict": "review", "confidence": 0.9, "reason": "no ref"}'
    )

    findings = validate_transactions(txns, gateway=gateway)

    assert len(findings) == 1
    assert findings[0].escalate is True


def test_confident_ok_verdict_does_not_escalate():
    txns = [_txn(txn_id="NOREF", reference=None)]
    gateway = MockLLMGateway(
        canned_response='{"verdict": "ok", "confidence": 0.95, "reason": "looks fine"}'
    )

    findings = validate_transactions(txns, gateway=gateway)

    assert len(findings) == 1
    assert findings[0].escalate is False


def test_validation_agent_node_emits_issues():
    txns = [_txn(txn_id="ZERO", amount="0")]

    update = validation_agent({"transactions": txns})

    assert len(update["validation_findings"]) == 1
    assert len(update["issues"]) == 1
    assert update["issues"][0].row_ref == "ZERO"
