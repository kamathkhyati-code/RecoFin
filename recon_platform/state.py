"""Shared graph state and message contracts for the Agentic Recon system."""

from __future__ import annotations

from datetime import datetime
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
    timestamp: datetime = Field(default_factory=datetime.utcnow)


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
    """Shared LangGraph state passed between all agent nodes."""

    run_id: str
    period: str
    messages: Annotated[list[AgentMessage], _append_messages]
    issues: list[IssueRecord]
    matched_count: int
    unmatched_count: int
    close_ready: bool
