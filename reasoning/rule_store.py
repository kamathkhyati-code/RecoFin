"""In-memory store for mined rule suggestions - B12.

Mirrors recon_platform.hitl.review_queue's pattern: the learning agent
proposes changes here; nothing changes matching behavior until an
analyst (or C12's wiring) approves a suggestion.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone

from reasoning.schemas import RuleSuggestion


@dataclass
class RuleStoreItem:
    item_id: int
    suggestion: RuleSuggestion
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    approved: bool = False


class RuleStore:
    """Tracks mined rule suggestions awaiting approval."""

    def __init__(self) -> None:
        self._items: dict[int, RuleStoreItem] = {}
        self._next_id = 1

    def add(self, suggestion: RuleSuggestion) -> RuleStoreItem:
        item = RuleStoreItem(item_id=self._next_id, suggestion=suggestion)
        self._items[item.item_id] = item
        self._next_id += 1
        return item

    def get(self, item_id: int) -> RuleStoreItem | None:
        return self._items.get(item_id)

    def pending(self) -> list[RuleStoreItem]:
        return [item for item in self._items.values() if not item.approved]

    def approved(self) -> list[RuleStoreItem]:
        return [item for item in self._items.values() if item.approved]

    def approve(self, item_id: int) -> None:
        item = self._items.get(item_id)
        if item is not None:
            item.approved = True


rule_store = RuleStore()
