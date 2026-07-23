from datetime import date
from decimal import Decimal

from datagents.schemas import Currency, SourceType, Transaction
from recon_platform.gateway.llm_gateway import MockLLMGateway
from reasoning.agents.semantic_match_agent import semantic_match
from reasoning.schemas import MatchType


def _txn(txn_id, amount, reference, source):
    return Transaction(
        txn_id=txn_id,
        date=date(2026, 6, 1),
        amount=Decimal(amount),
        currency=Currency.USD,
        counterparty="Acme Corp",
        reference=reference,
        source=source,
    )


def test_reworded_reference_matched_by_llm_path():
    book = [_txn("b1", "100.00", "Wire ref INV-2024-001", SourceType.CSV)]
    source = [_txn("s1", "100.00", "Payment for invoice 2024/001", SourceType.API)]

    gateway = MockLLMGateway(
        canned_response='{"is_match": true, "confidence": 0.9, "rationale": "same invoice, reworded"}'
    )

    results = semantic_match(book, source, gateway)

    assert len(results) == 1
    assert results[0].match_type == MatchType.SEMANTIC
    assert results[0].book_txn_id == "b1"
    assert results[0].source_txn_id == "s1"
    assert results[0].confidence == 0.9


def test_amount_mismatch_never_sent_to_llm():
    book = [_txn("b1", "100.00", "Wire ref INV-001", SourceType.CSV)]
    source = [_txn("s1", "500.00", "Payment for invoice 001", SourceType.API)]

    gateway = MockLLMGateway(
        canned_response='{"is_match": true, "confidence": 0.99, "rationale": "should never be called"}'
    )

    results = semantic_match(book, source, gateway)

    assert results == []
    assert gateway.usage.calls == 0


def test_low_confidence_llm_judgment_is_rejected():
    book = [_txn("b1", "100.00", "Wire ref INV-001", SourceType.CSV)]
    source = [_txn("s1", "100.00", "Unrelated payment", SourceType.API)]

    gateway = MockLLMGateway(
        canned_response='{"is_match": true, "confidence": 0.4, "rationale": "weak guess"}'
    )

    results = semantic_match(book, source, gateway, min_confidence=0.7)

    assert results == []


def test_output_schema_valid_shape():
    book = [_txn("b1", "50.00", "Ref A", SourceType.CSV)]
    source = [_txn("s1", "50.00", "Ref B", SourceType.API)]

    gateway = MockLLMGateway(
        canned_response='{"is_match": true, "confidence": 0.85, "rationale": "matched"}'
    )

    results = semantic_match(book, source, gateway)

    assert len(results) == 1
    result = results[0]
    assert 0.0 <= result.confidence <= 1.0
    assert result.rule == "semantic_llm"
    assert isinstance(result.rationale, str) and result.rationale
    assert result.metadata["reference_pair"] == ["Ref A", "Ref B"]
