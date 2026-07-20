from recon_platform.hitl.review_queue import ReviewQueue
from reasoning.agents.exception_escalation import (
    escalate_exceptions,
    needs_escalation,
    resolve_exception,
)
from reasoning.schemas import ExceptionRecord, ExcType


def _record(txn_id, risk, side="book", exc_type=ExcType.MISSING):
    return ExceptionRecord(
        txn_id=txn_id,
        side=side,
        exc_type=exc_type,
        risk_score=risk,
        suggested_resolution="Investigate.",
    )


def test_high_risk_needs_escalation():
    assert needs_escalation(_record("b1", 0.8)) is True


def test_low_risk_does_not_need_escalation():
    assert needs_escalation(_record("b1", 0.2)) is False


def test_high_risk_exception_is_escalated_to_queue():
    queue = ReviewQueue()
    records = [_record("b1", 0.8)]

    summary = escalate_exceptions(records, run_id="run-1", queue=queue)

    assert summary["escalated"] == ["b1"]
    assert len(queue.pending()) == 1


def test_low_risk_exception_is_auto_resolved_not_queued():
    queue = ReviewQueue()
    records = [_record("b1", 0.2)]

    summary = escalate_exceptions(records, run_id="run-1", queue=queue)

    assert summary["auto_resolved"] == ["b1"]
    assert summary["escalated"] == []
    assert queue.pending() == []


def test_escalating_same_exception_twice_does_not_duplicate():
    queue = ReviewQueue()
    records = [_record("b1", 0.8)]

    first = escalate_exceptions(records, run_id="run-1", queue=queue)
    second = escalate_exceptions(records, run_id="run-1", queue=queue)

    assert first["escalated"] == ["b1"]
    assert second["escalated"] == []
    assert second["already_queued"] == ["b1"]
    assert len(queue.pending()) == 1


def test_same_txn_id_on_different_sides_are_separate_entries():
    queue = ReviewQueue()
    records = [_record("t1", 0.8, side="book"), _record("t1", 0.8, side="source")]

    summary = escalate_exceptions(records, run_id="run-1", queue=queue)

    assert len(summary["escalated"]) == 2
    assert len(queue.pending()) == 2


def test_resolve_exception_clears_it_from_pending():
    queue = ReviewQueue()
    record = _record("b1", 0.8)
    escalate_exceptions([record], run_id="run-1", queue=queue)
    assert len(queue.pending()) == 1

    resolved = resolve_exception(record, run_id="run-1", analyst_note="Confirmed with bank.", queue=queue)

    assert queue.pending() == []
    assert resolved.analyst_note == "Confirmed with bank."


def test_resolved_exception_is_not_requeued_on_rerun():
    queue = ReviewQueue()
    record = _record("b1", 0.8)

    escalate_exceptions([record], run_id="run-1", queue=queue)
    resolve_exception(record, run_id="run-1", analyst_note="Done.", queue=queue)
    summary = escalate_exceptions([record], run_id="run-1", queue=queue)

    assert summary["escalated"] == []
    assert summary["already_queued"] == ["b1"]
    assert queue.pending() == []
