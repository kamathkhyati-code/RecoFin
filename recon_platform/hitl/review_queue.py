"""In-memory review queue for runs paused awaiting human decision.

Backed by run_id since the checkpointer already persists full graph state;
this queue only tracks which runs are currently waiting on a human and
why, so a UI or CLI can list and act on them.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone


@dataclass
class ReviewItem:
    run_id: str
    reason: str
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    resolved: bool = False


class ReviewQueue:
    """Tracks runs paused for human review."""

    def __init__(self) -> None:
        self._items: dict[str, ReviewItem] = {}

    def add(self, run_id: str, reason: str) -> ReviewItem:
        item = ReviewItem(run_id=run_id, reason=reason)
        self._items[run_id] = item
        return item

    def get(self, run_id: str) -> ReviewItem | None:
        return self._items.get(run_id)

    def pending(self) -> list[ReviewItem]:
        return [item for item in self._items.values() if not item.resolved]

    def mark_resolved(self, run_id: str) -> None:
        item = self._items.get(run_id)
        if item is not None:
            item.resolved = True


review_queue = ReviewQueue()
