"""SLA enforcement on the Exception Management Agent.

Follow-up to the pitch-deck cross-check: "enforce SLAs" was claimed but
no deadline/breach mechanism existed anywhere in the review queue or
escalation code. This tests the risk-scaled SLA policy, ReviewItem's
deadline/breach calculation, ReviewQueue.breached(), and that
escalate_exceptions actually sets a deadline on real queue entries.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from reasoning.agents.exception_escalation import (
    ESCALATION_THRESHOLD,
    escalate_exceptions,
    sla_hours_for_risk,
)
from reasoning.schemas import ExcType, ExceptionRecord
from recon_platform.hitl.review_queue import ReviewItem, ReviewQueue


def test_sla_hours_scale_with_risk():
    assert sla_hours_for_risk(0.95) == 24.0
    assert sla_hours_for_risk(0.8) == 24.0
    assert sla_hours_for_risk(0.7) == 72.0
    assert sla_hours_for_risk(0.6) == 72.0
    assert sla_hours_for_risk(0.3) == 168.0


def test_review_item_with_no_sla_never_breaches():
    item = ReviewItem(run_id="r1", reason="paused")
    assert item.sla_deadline is None
    assert item.is_breached is False


def test_review_item_breaches_after_deadline_passes():
    # Backdate created_at so the deadline has already passed, rather than
    # waiting real hours -- deterministic without mocking the clock.
    past = datetime.now(timezone.utc) - timedelta(hours=30)
    item = ReviewItem(run_id="r2", reason="high risk", created_at=past, sla_hours=24.0)
    assert item.is_breached is True


def test_review_item_within_sla_is_not_breached():
    item = ReviewItem(run_id="r3", reason="fresh", sla_hours=24.0)
    assert item.is_breached is False


def test_resolved_item_is_never_breached_even_if_overdue():
    past = datetime.now(timezone.utc) - timedelta(hours=100)
    item = ReviewItem(run_id="r4", reason="old", created_at=past, sla_hours=24.0, resolved=True)
    assert item.is_breached is False


def test_review_queue_breached_lists_only_overdue_pending_items():
    q = ReviewQueue()
    overdue = q.add("overdue", reason="x", sla_hours=24.0)
    overdue.created_at = datetime.now(timezone.utc) - timedelta(hours=100)
    q.add("fresh", reason="y", sla_hours=24.0)
    q.add("no_sla", reason="z")

    breached_ids = {item.run_id for item in q.breached()}
    assert breached_ids == {"overdue"}


def test_escalate_exceptions_sets_sla_on_queue_entry():
    q = ReviewQueue()
    record = ExceptionRecord(
        txn_id="T1", side="book", exc_type=ExcType.MISSING,
        risk_score=0.9, suggested_resolution="Investigate",
    )
    assert record.risk_score >= ESCALATION_THRESHOLD

    escalate_exceptions([record], run_id="run-sla-test", queue=q)

    item = q.get("run-sla-test:book:T1")
    assert item is not None
    assert item.sla_hours == 24.0
    assert item.sla_deadline is not None


def test_auto_resolved_exception_never_gets_a_queue_entry_or_sla():
    q = ReviewQueue()
    record = ExceptionRecord(
        txn_id="T2", side="book", exc_type=ExcType.TIMING,
        risk_score=0.1, suggested_resolution="Wait",
    )
    assert record.risk_score < ESCALATION_THRESHOLD

    escalate_exceptions([record], run_id="run-sla-test-2", queue=q)

    assert q.get("run-sla-test-2:book:T2") is None
