"""Standalone conditional router functions for the recon graph.

Kept separate from build_graph() so each routing decision can be
unit-tested directly with synthetic state, without running the full graph.
"""

from __future__ import annotations

MAX_VALIDATION_RETRIES = 2


def _has_critical_issue(issues) -> bool:
    """A run-blocking issue: error severity with no row_ref.

    row_ref is set for a specific row's problem (a malformed CSV row, a
    rejected validation finding) -- expected noise in any real dataset,
    already excluded/flagged by the agent that found it, and not
    something re-ingesting the whole batch fixes. row_ref is None for a
    batch-level failure (source unreachable, file not found) -- exactly
    what the retry-then-escalate loop below exists for. Without this
    distinction, a single malformed row anywhere in the batch would
    retry ingestion twice (pointlessly -- the bad row is still bad) and
    then escalate the entire run to human review, blocking every clean
    row along with it.
    """
    return any(
        getattr(issue, "severity", None) == "error" and getattr(issue, "row_ref", None) is None
        for issue in issues
    )


def validation_gate(state: dict) -> str:
    """After validation: retry ingestion, escalate to HITL, or proceed.

    - No critical issues: proceed to normalization.
    - Critical issues present and retries remain: loop back to ingestion.
    - Critical issues present and retries exhausted: escalate to resolution (HITL).
    """
    issues = state.get("issues") or []
    if not _has_critical_issue(issues):
        return "normalization"

    retry_count = state.get("retry_count", 0)
    if retry_count < MAX_VALIDATION_RETRIES:
        return "ingestion"
    return "resolution"


def matched_gate(state: dict) -> str:
    """After matching: unresolved items escalate to resolution (HITL)."""
    return "resolution" if state.get("unmatched_count", 0) > 0 else "consolidation"


def close_ready_gate(state: dict) -> str:
    """After consolidation: learning loop runs only when close-ready."""
    return "learning" if state.get("close_ready") else "end"
