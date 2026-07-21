"""Matching sub-graph (B10) - compose matching -> exception classification.

A standalone, testable unit that threads book/source transactions through
deterministic matching (B4), optional LLM escalation on the leftovers (B5),
hallucination-guarded confidence calibration against match memory (B6/B7),
and exception classification + risk scoring on whatever is still unmatched
(B8) - proving the pieces compose correctly on real state before the real
LangGraph wiring happens at integration (B11).
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from datagents.schemas import Transaction
from recon_platform.gateway.llm_gateway import LLMGateway
from reasoning.agents.calibrated_matcher import calibrate_matches
from reasoning.agents.exception_agent import exception_agent
from reasoning.agents.matching_agent import run_matching
from reasoning.agents.semantic_match_agent import semantic_match

if TYPE_CHECKING:
    # Type-only: importing chromadb (via MatchMemory) is expensive and
    # unnecessary for callers that never pass a memory store (the default).
    from reasoning.memory.match_memory import MatchMemory


def run_match_subgraph(
    state: dict[str, Any],
    *,
    gateway: LLMGateway | None = None,
    memory: MatchMemory | None = None,
) -> dict[str, Any]:
    """Run matching -> exception classification in sequence on `state`.

    Returns the merged state: match_results, unmatched_book, unmatched_source,
    and exceptions. LLM escalation only runs if a gateway is supplied; memory
    calibration only runs if a memory store is supplied, so the sub-graph is
    fully testable on deterministic golden data alone.
    """
    working: dict[str, Any] = dict(state)
    book: list[Transaction] = working.get("book_transactions", []) or []
    source: list[Transaction] = working.get("source_transactions", []) or []

    matches, unmatched_book, unmatched_source = run_matching(book, source)

    if gateway is not None and unmatched_book and unmatched_source:
        semantic_matches = semantic_match(unmatched_book, unmatched_source, gateway)
        matched_book_ids = {m.book_txn_id for m in semantic_matches}
        matched_source_ids = {m.source_txn_id for m in semantic_matches}
        unmatched_book = [t for t in unmatched_book if t.txn_id not in matched_book_ids]
        unmatched_source = [t for t in unmatched_source if t.txn_id not in matched_source_ids]
        matches = matches + semantic_matches

    matches = calibrate_matches(matches, book, source, memory=memory)
    exceptions = exception_agent(unmatched_book, unmatched_source)

    working["match_results"] = matches
    working["unmatched_book"] = unmatched_book
    working["unmatched_source"] = unmatched_source
    working["exceptions"] = exceptions
    return working
