"""Tests for A5 ingestion resilience (with_retry)."""
from __future__ import annotations

import pytest

from datagents.resilience import FetchError, with_retry


def test_retries_then_succeeds_on_transient_failure():
    calls = {"n": 0}

    def flaky():
        calls["n"] += 1
        if calls["n"] < 3:
            raise FetchError("transient blip")
        return "ok"

    result = with_retry(flaky, retries=5, base_delay=0, sleep=lambda _: None)

    assert result == "ok"
    assert calls["n"] == 3


def test_reraises_after_exhausting_retries():
    calls = {"n": 0}

    def always_down():
        calls["n"] += 1
        raise FetchError("source down")

    with pytest.raises(FetchError):
        with_retry(always_down, retries=3, base_delay=0, sleep=lambda _: None)

    assert calls["n"] == 3


def test_non_fetcherror_is_not_retried():
    calls = {"n": 0}

    def permanent_bug():
        calls["n"] += 1
        raise ValueError("not transient")

    with pytest.raises(ValueError):
        with_retry(permanent_bug, sleep=lambda _: None)

    assert calls["n"] == 1


def test_attempts_out_records_total_attempts_on_success():
    calls = {"n": 0}

    def flaky():
        calls["n"] += 1
        if calls["n"] < 3:
            raise FetchError("transient blip")
        return "ok"

    attempts: list[int] = []
    result = with_retry(flaky, retries=5, base_delay=0, sleep=lambda _: None, attempts_out=attempts)

    assert result == "ok"
    assert attempts == [3]


def test_attempts_out_records_total_attempts_on_exhaustion():
    def always_down():
        raise FetchError("source down")

    attempts: list[int] = []
    with pytest.raises(FetchError):
        with_retry(always_down, retries=3, base_delay=0, sleep=lambda _: None, attempts_out=attempts)

    assert attempts == [3]


def test_attempts_out_is_untouched_when_none():
    # Default behavior (no attempts_out) must be unaffected -- this is
    # what every existing caller/test relies on.
    result = with_retry(lambda: "ok", sleep=lambda _: None)
    assert result == "ok"
