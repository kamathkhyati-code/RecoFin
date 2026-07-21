"""Close-period gate (C14).

Full HITL cycle: exception -> review (B9's escalate_exceptions) -> resume
(review_queue.mark_resolved / B9's resolve_exception) -> consolidate
(close_ready computed from the live queue, see build.py's
consolidation_node) -> close. This module is the last step: an explicit,
enforced guard so a caller can't just ignore close_ready and treat a run
as closed while exceptions are still pending review.
"""

from __future__ import annotations

from reasoning.schemas import ReconReport


class PrematureCloseError(Exception):
    """Raised when closing a period is attempted while exceptions are still pending review."""


def close_period(report: ReconReport) -> None:
    """Close the period. Raises PrematureCloseError if report.close_ready is False."""
    if not report.close_ready:
        raise PrematureCloseError(
            f"Cannot close run {report.run_id}: {report.exception_count} exception(s) "
            f"still pending review, close_ready is False."
        )
