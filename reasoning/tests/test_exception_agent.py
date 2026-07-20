from datetime import date
from decimal import Decimal

from datagents.schemas import Currency, SourceType, Transaction
from reasoning.agents.exception_agent import (
    classify_exception,
    exception_agent,
    score_risk,
    suggest_resolution,
)
from reasoning.schemas import ExcType


def _txn(txn_id, amount="100.00", txn_date=date(2026, 6, 1), currency=Currency.USD, source=SourceType.CSV):
    return Transaction(
        txn_id=txn_id,
        date=txn_date,
        amount=Decimal(amount),
        currency=currency,
        counterparty="Acme Corp",
        reference="Ref",
        source=source,
    )


def test_classify_missing_when_no_counterparts():
    txn = _txn("b1")
    assert classify_exception(txn, []) == ExcType.MISSING


def test_classify_timing_same_amount_few_days_apart():
    txn = _txn("b1", "100.00", date(2026, 6, 1))
    counterpart = _txn("s1", "100.00", date(2026, 6, 3), source=SourceType.API)
    assert classify_exception(txn, [counterpart]) == ExcType.TIMING


def test_classify_fx_same_amount_different_currency():
    txn = _txn("b1", "100.00", date(2026, 6, 1), currency=Currency.USD)
    counterpart = _txn("s1", "100.00", date(2026, 6, 1), currency=Currency.EUR, source=SourceType.API)
    assert classify_exception(txn, [counterpart]) == ExcType.FX


def test_classify_mismatch_same_date_close_amount():
    txn = _txn("b1", "100.00", date(2026, 6, 1))
    counterpart = _txn("s1", "103.00", date(2026, 6, 1), source=SourceType.API)
    assert classify_exception(txn, [counterpart]) == ExcType.MISMATCH


def test_risk_score_missing_higher_than_timing():
    txn = _txn("b1", "100.00")
    assert score_risk(txn, ExcType.MISSING) > score_risk(txn, ExcType.TIMING)


def test_risk_score_lifted_for_material_amount():
    small = _txn("b1", "100.00")
    large = _txn("b2", "50000.00")
    assert score_risk(large, ExcType.MISMATCH) > score_risk(small, ExcType.MISMATCH)


def test_risk_score_stays_within_bounds():
    large = _txn("b1", "999999.00")
    score = score_risk(large, ExcType.MISSING)
    assert 0.0 <= score <= 1.0


def test_every_exc_type_has_a_resolution():
    for exc_type in ExcType:
        suggestion = suggest_resolution(exc_type)
        assert isinstance(suggestion, str) and suggestion


def test_exception_agent_covers_both_sides():
    book = [_txn("b1", "100.00")]
    source = [_txn("s1", "250.00", source=SourceType.API)]

    records = exception_agent(book, source)

    assert len(records) == 2
    sides = {r.side for r in records}
    assert sides == {"book", "source"}
    for record in records:
        assert 0.0 <= record.risk_score <= 1.0
        assert record.suggested_resolution


def _case(bid, amt, bdate, sid, samt, sdate, scur=Currency.USD, bcur=Currency.USD):
    b = _txn(bid, amt, bdate, currency=bcur)
    s = _txn(sid, samt, sdate, currency=scur, source=SourceType.API)
    return b, [s]


def test_classification_accuracy_on_labeled_set():
    cases = [
        (_txn("b1", "100.00", date(2026, 6, 1)), [], ExcType.MISSING),
        (_txn("b2", "500.00", date(2026, 6, 1)), [], ExcType.MISSING),
        (*_case("b3", "100.00", date(2026, 6, 1), "s3", "100.00", date(2026, 6, 3)), ExcType.TIMING),
        (*_case("b4", "750.00", date(2026, 6, 10), "s4", "750.00", date(2026, 6, 12)), ExcType.TIMING),
        (*_case("b5", "200.00", date(2026, 6, 1), "s5", "200.00", date(2026, 6, 1), scur=Currency.EUR), ExcType.FX),
        (*_case("b6", "1000.00", date(2026, 6, 5), "s6", "1000.00", date(2026, 6, 5), bcur=Currency.GBP), ExcType.FX),
        (*_case("b7", "100.00", date(2026, 6, 1), "s7", "102.50", date(2026, 6, 1)), ExcType.MISMATCH),
        (*_case("b8", "440.00", date(2026, 6, 20), "s8", "444.00", date(2026, 6, 20)), ExcType.MISMATCH),
        (*_case("b9", "100.00", date(2026, 6, 1), "s9", "8000.00", date(2026, 12, 25)), ExcType.UNKNOWN),
        (*_case("b10", "60.00", date(2026, 6, 1), "s10", "9500.00", date(2026, 11, 1)), ExcType.UNKNOWN),
    ]
    correct = sum(1 for t, pool, exp in cases if classify_exception(t, pool) == exp)
    accuracy = correct / len(cases)
    assert accuracy >= 0.9, f"accuracy {accuracy:.0%} below 90% ({correct}/{len(cases)})"
