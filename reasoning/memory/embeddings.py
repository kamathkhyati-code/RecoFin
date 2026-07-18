"""Deterministic, dependency-free text embedding for match memory.
Uses feature hashing instead of a downloaded sentence-transformer model,
so match_memory never needs network access or a model download, only
pure Python. Crude, but consistent: text sharing words reliably lands
close together in the vector space, which is all nearest-neighbour
retrieval here needs.
"""
from __future__ import annotations

import hashlib
import math

_DIM = 64


def _tokenize(text: str) -> list[str]:
    return "".join(c.lower() if c.isalnum() else " " for c in text).split()


def embed(text: str, dim: int = _DIM) -> list[float]:
    vector = [0.0] * dim
    for token in _tokenize(text):
        h = int(hashlib.sha256(token.encode("utf-8")).hexdigest(), 16)
        vector[h % dim] += 1.0
    norm = math.sqrt(sum(v * v for v in vector))
    if norm == 0:
        return vector
    return [v / norm for v in vector]


class HashingEmbeddingFunction:
    """Chroma-compatible embedding function: list[str] -> list[list[float]]."""

    def __call__(self, input: list[str]) -> list[list[float]]:
        return [embed(text) for text in input]

    def embed_documents(self, input: list[str]) -> list[list[float]]:
        return self(input)

    def embed_query(self, input: list[str]) -> list[list[float]]:
        return self(input)

    def name(self) -> str:
        return "hashing_embedding_function"

    def is_legacy(self) -> bool:
        return False
