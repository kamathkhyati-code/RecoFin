"""Match memory (RAG) - B6.

Embeds confirmed matches (reference + counterparty text) and upserts them
into a Chroma collection. Given a new candidate pair, retrieves the
nearest historical matches so callers (B7's confidence calibration, or a
future memory-aware matching pass) can boost confidence when a similar
pair has been confirmed before.
"""

from __future__ import annotations

import chromadb

from datagents.schemas import Transaction
from reasoning.memory.embeddings import HashingEmbeddingFunction
from reasoning.schemas import MatchResult


def _pair_text(book_txn: Transaction, source_txn: Transaction) -> str:
    return f"{book_txn.counterparty} {book_txn.reference} | {source_txn.counterparty} {source_txn.reference}"


class MatchMemory:
    """Wraps a Chroma collection of confirmed book/source match pairs."""

    def __init__(self, client=None, collection_name: str = "match_memory"):
        self._client = client or chromadb.Client()
        self._collection = self._client.get_or_create_collection(
            name=collection_name,
            embedding_function=HashingEmbeddingFunction(),
        )

    def upsert_match(self, book_txn: Transaction, source_txn: Transaction, match: MatchResult) -> None:
        """Store a confirmed match pair so future similar pairs can be retrieved."""
        pair_id = f"{book_txn.txn_id}:{source_txn.txn_id}"
        self._collection.upsert(
            ids=[pair_id],
            documents=[_pair_text(book_txn, source_txn)],
            metadatas=[
                {
                    "book_txn_id": book_txn.txn_id,
                    "source_txn_id": source_txn.txn_id,
                    "match_type": match.match_type.value,
                    "rule": match.rule,
                }
            ],
        )

    def retrieve_nearest(
        self, book_txn: Transaction, source_txn: Transaction, n_results: int = 3
    ) -> list[dict]:
        """Return the nearest historical matches to this candidate pair.

        Each result dict has "distance" (lower = more similar) and
        "metadata" (the stored match info) so callers can decide whether
        the nearest neighbour is close enough to count as support.
        """
        query_text = _pair_text(book_txn, source_txn)
        result = self._collection.query(query_texts=[query_text], n_results=n_results)

        out = []
        distances = result.get("distances", [[]])[0]
        metadatas = result.get("metadatas", [[]])[0]
        for distance, metadata in zip(distances, metadatas):
            out.append({"distance": distance, "metadata": metadata})
        return out
