"""Exception escalation to the HITL review queue - B9.

Takes the ExceptionRecords produced by B8's exception_agent and decides
which ones need a human. High-risk exceptions are escalated onto the
shared review queue; low-risk ones are auto-dispositioned with their
suggested resolution and never reach an analyst.

Escalation is idempotent: escalating the same exception twice does not
create a second queue entry, so a re-run or a resumed graph never
duplicates analyst work.
"""

from __future__ import annotations

from recon_platform.hitl.review_queue import ReviewQueue, review_queue
from reasoning.schemas import ExceptionRecord

# Exceptions at or above this risk score need a human decision.
ESCALATION_THRESHOLD = 0.5


def _queue_key(run_id: str, record: ExceptionRecord) -> str:
    """Stable per-exception key so the same exception maps to one entry."""
    return f"{run_id}:{record.side}:{record.txn_id}"


def needs_escalation(record: ExceptionRecord, threshold: float = ESCALATION_THRESHOLD) -> bool:
    return record.risk_score >= threshold


def escalate_exceptions(
    records: list[ExceptionRecord],
    run_id: str,
    queue: ReviewQueue | None = None,
    threshold: float = ESCALATION_THRESHOLD,
) -> dict:
    """Escalate high-risk exceptions onto the review queue, idempotently.

    Returns a summary dict with the keys escalated, auto_resolved, and
    already_queued so callers can see what happened without inspecting
    the queue directly.
    """
    q = queue if queue is not None else review_queue

    escalated: list[str] = []
    auto_resolved: list[str] = []
    already_queued: list[str] = []

    for record in records:
        key = _queue_key(run_id, record)

        if not needs_escalation(record, threshold):
            auto_resolved.append(record.txn_id)
            continue

        if q.get(key) is not None:
            already_queued.append(record.txn_id)
            continue

        reason = (
            f"{record.exc_type.value} exception on {record.side} txn "
            f"{record.txn_id} (risk {record.risk_score}): {record.suggested_resolution}"
        )
        q.add(key, reason=reason)
        escalated.append(record.txn_id)

    return {
        "escalated": escalated,
        "auto_resolved": auto_resolved,
        "already_queued": already_queued,
    }


def resolve_exception(
    record: ExceptionRecord,
    run_id: str,
    analyst_note: str,
    queue: ReviewQueue | None = None,
) -> ExceptionRecord:
    """Mark an escalated exception resolved and attach the analyst's note."""
    q = queue if queue is not None else review_queue
    q.mark_resolved(_queue_key(run_id, record))
    return record.model_copy(update={"analyst_note": analyst_note})
