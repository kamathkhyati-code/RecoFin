"""Matching Agent (deterministic).

Resolves its strategy tools from the shared ToolRegistry and runs them
strongest-first (exact -> tolerance -> fuzzy), retiring matched transactions
between passes, then returns matches plus the leftover book/source
transactions. LLM + RAG escalation (B5/B6) is Intern C's work and plugs in
after this deterministic pass.
"""
from __future__ import annotations

from datagents.schemas import Transaction
from recon_platform.registry import registry
from recon_platform.state import AgentMessage, MessageRole, ReconState
from reasoning.schemas import MatchResult
from reasoning.tools import matching_tools  # noqa: F401  registers matching tools

# Strategy tool names in strongest-first order (resolved from the registry).
_STRATEGY_NAMES = ("exact_tool", "tolerance_tool", "fuzzy_tool")


def run_matching(
    book: list[Transaction], source: list[Transaction]
) -> tuple[list[MatchResult], list[Transaction], list[Transaction]]:
    """Match book vs source strongest-first; return matches + leftovers."""
    remaining_book = list(book)
    remaining_source = list(source)
    matches: list[MatchResult] = []

    for name in _STRATEGY_NAMES:
        if not remaining_book or not remaining_source:
            break
        strategy = registry.get(name).func
        found = strategy(remaining_book, remaining_source)
        if not found:
            continue
        matches.extend(found)
        matched_book = {m.book_txn_id for m in found}
        matched_source = {m.source_txn_id for m in found}
        remaining_book = [
            t for t in remaining_book if t.txn_id not in matched_book
        ]
        remaining_source = [
            t for t in remaining_source if t.txn_id not in matched_source
        ]

    return matches, remaining_book, remaining_source


def matching_agent(state: ReconState) -> dict:
    """LangGraph node: match normalized book vs source transactions."""
    book: list[Transaction] = state.get("book_transactions", []) or []
    source: list[Transaction] = state.get("source_transactions", []) or []

    matches, unmatched_book, unmatched_source = run_matching(book, source)
    unmatched_total = len(unmatched_book) + len(unmatched_source)

    content = (
        f"Matched {len(matches)} pair(s); "
        f"{len(unmatched_book)} book and {len(unmatched_source)} source left."
    )
    return {
        "match_results": matches,
        "unmatched_book": unmatched_book,
        "unmatched_source": unmatched_source,
        "matched_count": len(matches),
        "unmatched_count": unmatched_total,
        "messages": [
            AgentMessage(role=MessageRole.MATCHING, content=content)
        ],
    }
