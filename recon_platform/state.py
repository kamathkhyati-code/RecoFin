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

    Declared here for documentation/type-safety only; TypedDict isn't
    enforced at runtime, so a node writing an undeclared key still works.
    Kept as `Any` rather than importing datagents/reasoning types directly,
    since recon_platform is the shared platform layer both packages depend
    on, not the other way around.

    data-agent fields (A10/A11): transactions, source_configs,
    normalized_transactions, validation_findings.
    matching/exception fields (B10/B11): book_transactions,
    source_transactions, match_results, unmatched_book, unmatched_source,
    exceptions.
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

    # Consolidation state (C track, C11)
    report: Any
