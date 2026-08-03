"""In-memory review queue for runs paused awaiting human decision.

Backed by run_id since the checkpointer already persists full graph state;
this queue only tracks which runs are currently waiting on a human and
why, so a UI or CLI can list and act on them.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone


@dataclass
class ReviewItem:
    run_id: str
    reason: str
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    resolved: bool = False
    # SLA enforcement: hours this item has to be resolved before it counts
    # as breached. None means untracked (e.g. the plain HITL-pause entries
    # from hitl/resume.py, which aren't risk-scored exceptions and have no
    # natural SLA basis) -- not every queue entry needs one.
    sla_hours: float | None = None

    @property
    def sla_deadline(self) -> datetime | None:
        if self.sla_hours is None:
            return None
        return self.created_at + timedelta(hours=self.sla_hours)

    @property
    def is_breached(self) -> bool:
        """True if still unresolved and past its SLA deadline. Resolved
        items are never breached, even if resolved late -- breach is about
        what still needs attention right now, not a historical audit of
        how long resolution took."""
        deadline = self.sla_deadline
        if self.resolved or deadline is None:
            return False
        return datetime.now(timezone.utc) > deadline


class ReviewQueue:
    """Tracks runs paused for human review."""

    def __init__(self) -> None:
        self._items: dict[str, ReviewItem] = {}

    def add(self, run_id: str, reason: str, sla_hours: float | None = None) -> ReviewItem:
        item = ReviewItem(run_id=run_id, reason=reason, sla_hours=sla_hours)
        self._items[run_id] = item
        return item

    def get(self, run_id: str) -> ReviewItem | None:
        return self._items.get(run_id)

    def pending(self) -> list[ReviewItem]:
        return [item for item in self._items.values() if not item.resolved]

    def breached(self) -> list[ReviewItem]:
        """Pending items past their SLA deadline -- what 'enforce SLAs'
        actually means here: surfacing what's overdue, not just recording
        a deadline nobody checks. No notification channel exists in this
        system, so enforcement stops at visibility, not auto-alerting."""
        return [item for item in self.pending() if item.is_breached]

    def mark_resolved(self, run_id: str) -> None:
        item = self._items.get(run_id)
        if item is not None:
            item.resolved = True


review_queue = ReviewQueue()


def pending_for_run(run_id: str, queue: ReviewQueue | None = None) -> list[ReviewItem]:
    """Pending items for a specific graph run_id.

    B9's exception_escalation keys queue items as "{run_id}:{side}:{txn_id}"
    (one entry per exception) rather than the plain run_id this queue was
    originally keyed by (one entry per paused run, see hitl/resume.py) --
    this filters by prefix to find only this run's still-pending
    exceptions, which is what C14's close_ready check needs: "exceptions
    resolved", not "run un-paused".
    """
    q = queue if queue is not None else review_queue
    prefix = f"{run_id}:"
    return [item for item in q.pending() if item.run_id.startswith(prefix)]
