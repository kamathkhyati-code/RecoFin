"""Reasoning-track schemas: match results, exceptions, report, rule suggestions.

Owned by Intern B (matching spine). Consumed by Intern C's HITL, learning,
and consolidation agents. Transaction references are string IDs so this
module stays decoupled from datagents.schemas.Transaction.
"""
from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum

from pydantic import BaseModel, Field


class MatchType(str, Enum):
    """How a pair of transactions was matched, strongest to weakest."""

    EXACT = "exact"
    TOLERANCE = "tolerance"
    FUZZY = "fuzzy"
    MEMORY = "memory"
    SEMANTIC = "semantic"


class ExcType(str, Enum):
    """Why a transaction could not be matched."""

    MISSING = "missing"
    MISMATCH = "mismatch"
    FX = "fx"
    TIMING = "timing"
    UNKNOWN = "unknown"


class MatchResult(BaseModel):
    """A single confirmed pairing of a book txn to a source txn."""

    book_txn_id: str
    source_txn_id: str
    match_type: MatchType
    confidence: float = Field(ge=0.0, le=1.0)
    rule: str
    rationale: str = ""
    metadata: dict = Field(default_factory=dict)


class ExceptionRecord(BaseModel):
    """An unmatched transaction, classified and risk-scored."""

    txn_id: str
    side: str
    exc_type: ExcType = ExcType.UNKNOWN
    risk_score: float = Field(default=0.0, ge=0.0, le=1.0)
    suggested_resolution: str | None = None
    analyst_note: str | None = None
    rationale: str = ""


class RuleSuggestion(BaseModel):
    """A mined rule change proposed by the learning agent."""

    rule_type: str
    description: str
    suggested_params: dict = Field(default_factory=dict)
    support_count: int = 0
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    rationale: str = ""


class ReconReport(BaseModel):
    """Run-level summary produced at consolidation."""

    run_id: str
    period: str
    matched_count: int = 0
    unmatched_count: int = 0
    exception_count: int = 0
    match_rate: float = Field(default=0.0, ge=0.0, le=1.0)
    close_ready: bool = False
    generated_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc)
    )
