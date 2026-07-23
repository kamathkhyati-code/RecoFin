from datetime import date
from decimal import Decimal

import chromadb

from datagents.schemas import Currency, SourceType, Transaction
from reasoning.memory.match_memory import MatchMemory
from reasoning.schemas import MatchResult, MatchType


def _txn(txn_id, amount, reference, counterparty="Acme Corp", source=SourceType.CSV):
    return Transaction(
        txn_id=txn_id,
        date=date(2026, 6, 1),
        amount=Decimal(amount),
        currency=Currency.USD,
        counterparty=counterparty,
        reference=reference,
        source=source,
    )


def _fresh_memory():
    client = chromadb.EphemeralClient()
    return MatchMemory(client=client, collection_name="test_match_memory")


def test_known_pair_retrieved_as_nearest_neighbour():
    memory = _fresh_memory()

    book = _txn("b1", "100.00", "Wire ref INV-2024-001")
    source = _txn("s1", "100.00", "Payment for invoice 2024/001", source=SourceType.API)
    match = MatchResult(
        book_txn_id="b1",
        source_txn_id="s1",
        match_type=MatchType.SEMANTIC,
        confidence=0.9,
        rule="semantic_llm",
    )
    memory.upsert_match(book, source, match)

    query_book = _txn("b2", "100.00", "Wire ref INV-2024-001")
    query_source = _txn("s2", "100.00", "Payment for invoice 2024/001", source=SourceType.API)

    results = memory.retrieve_nearest(query_book, query_source, n_results=1)

    assert len(results) == 1
    assert results[0]["metadata"]["book_txn_id"] == "b1"
    assert results[0]["metadata"]["source_txn_id"] == "s1"


def test_unrelated_pair_is_not_the_nearest_neighbour():
    memory = _fresh_memory()

    book = _txn("b1", "100.00", "Wire ref INV-2024-001")
    source = _txn("s1", "100.00", "Payment for invoice 2024/001", source=SourceType.API)
    match = MatchResult(
        book_txn_id="b1",
        source_txn_id="s1",
        match_type=MatchType.SEMANTIC,
        confidence=0.9,
        rule="semantic_llm",
    )
    memory.upsert_match(book, source, match)

    unrelated_book = _txn("b2", "50.00", "Office supplies purchase", counterparty="Staples")
    unrelated_source = _txn("s2", "50.00", "Office supplies", counterparty="Staples", source=SourceType.API)

    results = memory.retrieve_nearest(unrelated_book, unrelated_source, n_results=1)

    assert len(results) == 1
    same_distance_query = memory.retrieve_nearest(book, source, n_results=1)
    assert same_distance_query[0]["distance"] <= results[0]["distance"]


def test_upsert_is_idempotent_for_same_pair():
    memory = _fresh_memory()
    book = _txn("b1", "100.00", "Wire ref INV-001")
    source = _txn("s1", "100.00", "Payment INV-001", source=SourceType.API)
    match = MatchResult(book_txn_id="b1", source_txn_id="s1", match_type=MatchType.EXACT, confidence=1.0, rule="exact")
    memory.upsert_match(book, source, match)
    memory.upsert_match(book, source, match)
    results = memory.retrieve_nearest(book, source, n_results=5)
    matching_ids = [r["metadata"]["book_txn_id"] for r in results if r["metadata"]["book_txn_id"] == "b1"]
    assert len(matching_ids) == 1
