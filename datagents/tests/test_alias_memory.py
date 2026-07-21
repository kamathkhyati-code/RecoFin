"""Tests for A9: alias memory + idempotency."""
from __future__ import annotations
from datetime import date
from decimal import Decimal

from datagents.agents.normalization_agent import normalize_transactions
from datagents.schemas import Currency, SourceType, Transaction
from datagents.tools.alias_store import AliasStore
from datagents.tools.normalization_tools import entity_alias_tool


class _CountingGateway:
    """Fake LLM gateway that counts calls and returns a fixed canonical name."""

    def __init__(self, answer: str = "NEWCO") -> None:
        self.answer = answer
        self.calls = 0

    def generate(self, prompt: str) -> str:
        self.calls += 1
        return self.answer


def test_first_call_uses_llm_and_caches(tmp_path):
    store = AliasStore(tmp_path / "alias_cache.json")
    gateway = _CountingGateway("NEWCO")

    result = entity_alias_tool("Newco Holdings", gateway, store)

    assert result == "NEWCO"
    assert gateway.calls == 1
    assert store.get("NEWCO HOLDINGS") == "NEWCO"


def test_second_run_reads_cache_zero_llm_calls(tmp_path):
    cache_path = tmp_path / "alias_cache.json"

    store1 = AliasStore(cache_path)
    gateway1 = _CountingGateway("NEWCO")
    entity_alias_tool("Newco Holdings", gateway1, store1)
    assert gateway1.calls == 1

    store2 = AliasStore(cache_path)
    gateway2 = _CountingGateway("NEWCO")
    result = entity_alias_tool("Newco Holdings", gateway2, store2)

    assert result == "NEWCO"
    assert gateway2.calls == 0


def test_normalized_output_identical_across_runs(tmp_path):
    cache_path = tmp_path / "alias_cache.json"
    txns = [
        Transaction(
            txn_id="T1",
            date=date(2026, 1, 1),
            amount=Decimal("100.00"),
            currency=Currency.USD,
            counterparty="Newco Holdings",
            reference="INV-1",
            source=SourceType.CSV,
        )
    ]

    store1 = AliasStore(cache_path)
    gateway1 = _CountingGateway("NEWCO")
    run1 = normalize_transactions(txns, gateway=gateway1, store=store1)

    store2 = AliasStore(cache_path)
    gateway2 = _CountingGateway("NEWCO")
    run2 = normalize_transactions(txns, gateway=gateway2, store=store2)

    assert gateway1.calls == 1
    assert gateway2.calls == 0
    assert run1 == run2
