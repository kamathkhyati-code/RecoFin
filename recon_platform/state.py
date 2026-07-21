"""Shared graph state and message contracts for the Agentic Recon system."""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Annotated, Any, TypedDict

from pydantic import BaseModel, Field


class MessageRole(str, Enum):
    SUPERVISOR = "supervisor"
    INGESTION = "ingestion"
    VALIDATION = "validation"
    NORMALIZATION = "normalization"
    MATCHING = "matching"
    RESOLUTION = "resolution"
    CONSOLIDATION = "consolidation"
    LEARNING = "learning"
    HUMAN = "human"


class AgentMessage(BaseModel):
    """A single message contract passed between agents in the graph."""

    role: MessageRole
    content: str
    payload: dict[str, Any] = Field(default_factory=dict)
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class IssueRecord(BaseModel):
    """A single validation/reconciliation issue raised by any agent."""

    source: str
    severity: str = "warning"
    message: str
    row_ref: str | None = None


def _append_messages(left: list[AgentMessage], right: list[AgentMessage]) -> list[AgentMessage]:
    """Reducer: append new messages to the running message log (LangGraph convention)."""
    return left + right


class ReconState(TypedDict, total=False):
    """Shared LangGraph state passed between all agent nodes.

    Every key a node needs to read or write must be declared here.
    Correction (A13): the class docstring previously claimed a node could
    write an undeclared key and it would "still work" -- that's true for a
    plain dict, but NOT for a compiled StateGraph(ReconState): LangGraph
    builds one channel per schema field, and silently drops any key a node
    returns (or any key on the initial input state) that isn't declared
    here. Confirmed empirically while wiring A13's ingestion_metrics, which
    surfaced a second, more serious instance of the same gap:
    book_source_configs/bank_source_configs (A11) had never been declared
    either, so the real configs-driven ingestion path silently never ran
    through an actual graph.invoke() call, even though every existing test
    passed (none of them exercised that exact path end-to-end).
    Kept as `Any` rather than importing datagents/reasoning types directly,
    since recon_platform is the shared platform layer both packages depend
    on, not the other way around.

    data-agent fields (A10/A11): transactions, source_configs,
    book_source_configs, bank_source_configs, normalized_transactions,
    validation_findings.
    matching/exception fields (B10/B11): book_transactions,
    source_transactions, match_results, unmatched_book, unmatched_source,
    exceptions.
    ingestion observability (A13): ingestion_metrics.
    """

    run_id: str
    period: str
    messages: Annotated[list[AgentMessage], _append_messages]
    issues: list[IssueRecord]
    matched_count: int
    unmatched_count: int
    close_ready: bool
    retry_count: int

    # Data-agent state (A track)
    source_configs: list[Any]
    book_source_configs: list[Any]
    bank_source_configs: list[Any]
    transactions: list[Any]
    validation_findings: list[Any]
    normalized_transactions: list[Any]

    # Matching/exception state (B track)
    book_transactions: list[Any]
    source_transactions: list[Any]
    match_results: list[Any]
    unmatched_book: list[Any]
    unmatched_source: list[Any]
    exceptions: list[Any]

    # Ingestion observability (A13)
    ingestion_metrics: list[Any]

    # Consolidation state (C track, C11)
    report: Any

    # Learning loop state (B12/C12)
    rule_suggestions: list[Any]
