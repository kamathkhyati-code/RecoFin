"""Semantic matching agent (LLM path) - B5.

Escalates sub-threshold pairs (same amount + currency, but reference
wording too different for fuzzy_tool's string-similarity threshold) to an
LLM via the shared gateway. The guardrail retry mechanism validates the
LLM's output against a strict schema before it becomes a MatchResult.

Deterministic always wins: this only ever runs against whatever
matching_agent has already left unmatched after its exact/tolerance/fuzzy
passes, so a pair the deterministic tools already caught is never
re-examined here.
"""

from __future__ import annotations

from decimal import Decimal

from pydantic import BaseModel, Field

from datagents.schemas import Transaction
from recon_platform.gateway.llm_gateway import LLMGateway
from recon_platform.guardrails.injection_guard import any_field_looks_like_injection
from recon_platform.guardrails.validators import validate_with_retry
from reasoning.schemas import MatchResult, MatchType


class SemanticJudgment(BaseModel):
    """Structured LLM output for one candidate pair."""

    is_match: bool
    confidence: float = Field(ge=0.0, le=1.0)
    rationale: str


def _build_prompt(book_txn: Transaction, source_txn: Transaction) -> str:
    parts = []
    parts.append("Decide whether these two transactions refer to the same")
    parts.append("underlying payment, despite differently worded references.")
    parts.append('Respond as JSON: {"is_match": bool, "confidence": float 0-1, "rationale": str}.')
    parts.append("")
    parts.append(f"Book txn: amount={book_txn.amount} {book_txn.currency.value}, date={book_txn.date}, counterparty='{book_txn.counterparty}', reference='{book_txn.reference}'")
    parts.append(f"Source txn: amount={source_txn.amount} {source_txn.currency.value}, date={source_txn.date}, counterparty='{source_txn.counterparty}', reference='{source_txn.reference}'")
    return "\n".join(parts)


def semantic_match(
    book: list[Transaction],
    source: list[Transaction],
    gateway: LLMGateway,
    amount_tol: Decimal = Decimal("0.01"),
    min_confidence: float = 0.7,
) -> list[MatchResult]:
    """Escalate remaining book/source pairs to the LLM, same-amount pairs only.

    Only pairs with identical currency and amount within tolerance are sent
    to the LLM at all, this keeps the LLM judging wording, not numbers.
    """
    results: list[MatchResult] = []
    used_book: set[str] = set()
    used_source: set[str] = set()

    for b in book:
        if b.txn_id in used_book:
            continue
        for s in source:
            if s.txn_id in used_source:
                continue
            if b.currency != s.currency:
                continue
            if abs(b.amount - s.amount) > amount_tol:
                continue
            if any_field_looks_like_injection(b.reference, b.counterparty, s.reference, s.counterparty):
                # C17: a field looks like it's trying to manipulate the
                # model -- never send it to the LLM. Falls through to
                # exception handling for human review instead of trusting
                # the model to resist the injection.
                continue

            prompt = _build_prompt(b, s)
            judgment = validate_with_retry(
                SemanticJudgment, lambda p=prompt: gateway.generate(p)
            )

            if judgment.is_match and judgment.confidence >= min_confidence:
                results.append(
                    MatchResult(
                        book_txn_id=b.txn_id,
                        source_txn_id=s.txn_id,
                        match_type=MatchType.SEMANTIC,
                        confidence=judgment.confidence,
                        rule="semantic_llm",
                        rationale=judgment.rationale,
                        metadata={"reference_pair": [b.reference, s.reference]},
                    )
                )
                used_book.add(b.txn_id)
                used_source.add(s.txn_id)
                break

    return results
