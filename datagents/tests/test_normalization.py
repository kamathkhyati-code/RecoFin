"""Tests for the A8 Normalization Agent and its tools."""
from __future__ import annotations

from datetime import date
from decimal import Decimal

from datagents.agents.normalization_agent import normalize_transactions
from datagents.schemas import Currency, SourceType, Transaction
from datagents.tools.normalization_tools import (
    canonicalize_reference,
    entity_alias_tool,
    fx_rate_tool,
)
from recon_platform.gateway.llm_gateway import MockLLMGateway


def test_fx_gbp_to_usd_exact_to_the_cent():
    assert fx_rate_tool(Decimal("900.00"), Currency.GBP) == Decimal("1143.00")


def test_fx_usd_to_usd_is_identity():
    assert fx_rate_tool(Decimal("250.00"), Currency.USD) == Decimal("250.00")


def test_entity_alias_resolves_known_variant():
    assert entity_alias_tool("ACME-UK") == "ACME"
    assert entity_alias_tool("globex llc") == "GLOBEX"


def test_entity_alias_uses_llm_for_unknown_name():
    gateway = MockLLMGateway(canned_response="NEWCO")
    assert entity_alias_tool("Newco Holdings Ltd", gateway=gateway) == "NEWCO"


def test_reference_canonical_form():
    assert canonicalize_reference("inv-1001") == "INV-1001"
    assert canonicalize_reference("  ref-9 ") == "REF-9"
    assert canonicalize_reference(None) is None


def test_normalize_transactions_end_to_end():
    txn = Transaction(
        txn_id="T1",
        date=date(2026, 1, 1),
        amount=Decimal("900.00"),
        currency=Currency.GBP,
        counterparty="ACME-UK",
        reference="inv-1001",
        source=SourceType.CSV,
    )

    [normalized] = normalize_transactions([txn])

    assert normalized.currency == Currency.USD
    assert normalized.amount == Decimal("1143.00")
    assert normalized.counterparty == "ACME"
    assert normalized.reference == "INV-1001"
    # original left untouched
    assert txn.amount == Decimal("900.00")
    assert txn.counterparty == "ACME-UK"
