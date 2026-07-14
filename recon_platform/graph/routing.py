"""Standalone conditional router functions for the recon graph.

Kept separate from build_graph() so each routing decision can be
unit-tested directly with synthetic state, without running the full graph.
"""

from __future__ import annotations

MAX_VALIDATION_RETRIES = 2


def _has_critical_issue(issues) -> bool:
    return any(getattr(issue, "severity", None) == "error" for issue in issues)


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
