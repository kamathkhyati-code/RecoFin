"""Ingestion resilience (A5) — retry a transient source fetch with backoff.

Source fetches can fail transiently (network blips, a momentarily unavailable
API/SFTP). `with_retry` re-runs the callable on `FetchError` with exponential
backoff, emits a structured log line per attempt, and re-raises the last error
once attempts are exhausted. `sleep` is injectable so tests run instantly.

A13: `attempts_out`, if given a list, gets the total attempt count appended
to it once the call resolves (succeeds or exhausts retries) -- lets a caller
(ingestion_agent) record retry metrics without with_retry needing to know
anything about metrics/observability itself.

A16: RateLimiter enforces a minimum interval between consecutive calls to
the same source -- e.g. a real SAP/Oracle/bank API that would throttle or
ban a client hammering it on every retry attempt. Separate from with_retry
(backoff delays a specific failed call; RateLimiter paces every call,
successful or not) and separate from FetchError/timeouts (a source can be
healthy and still need pacing).
"""
from __future__ import annotations

import logging
import time
from collections.abc import Callable
from typing import TypeVar

logger = logging.getLogger("datagents.ingestion.retry")

T = TypeVar("T")


class FetchError(Exception):
    """A transient failure while fetching from a source (safe to retry)."""


def with_retry(
    fn: Callable[[], T],
    *,
    retries: int = 3,
    base_delay: float = 0.5,
    sleep: Callable[[float], None] = time.sleep,
    attempts_out: list[int] | None = None,
) -> T:
    """Call `fn`, retrying on FetchError with exponential backoff.

    Makes up to `retries` total attempts. The delay before retry n (1-indexed)
    is base_delay * 2 ** (n - 1). Re-raises the last FetchError if every
    attempt fails; non-FetchError exceptions propagate immediately (not retried).
    """
    attempt = 0
    while True:
        try:
            result = fn()
            if attempts_out is not None:
                attempts_out.append(attempt + 1)
            return result
        except FetchError as exc:
            attempt += 1
            if attempt >= retries:
                logger.error(
                    "fetch_retry_exhausted",
                    extra={"attempt": attempt, "retries": retries, "error": str(exc)},
                )
                if attempts_out is not None:
                    attempts_out.append(attempt)
                raise
            delay = base_delay * (2 ** (attempt - 1))
            logger.warning(
                "fetch_retry",
                extra={"attempt": attempt, "delay": delay, "error": str(exc)},
            )
            sleep(delay)


class RateLimiter:
    """Enforces a minimum interval between consecutive `wait()` calls.

    Stateful and per-instance: share one RateLimiter across calls to the
    same source to pace them; use a separate instance (or none) per source
    to avoid one slow-moving source throttling an unrelated one.

    `sleep`/`now` are injectable so tests can verify pacing without a real
    test taking wall-clock seconds.
    """

    def __init__(
        self,
        min_interval_seconds: float,
        *,
        sleep: Callable[[float], None] = time.sleep,
        now: Callable[[], float] = time.monotonic,
    ) -> None:
        self.min_interval_seconds = min_interval_seconds
        self._sleep = sleep
        self._now = now
        self._last_call: float | None = None

    def wait(self) -> None:
        """Block (via injected sleep) until min_interval_seconds have
        elapsed since the last wait() call, then record this call's time.
        """
        now = self._now()
        if self._last_call is not None:
            elapsed = now - self._last_call
            remaining = self.min_interval_seconds - elapsed
            if remaining > 0:
                self._sleep(remaining)
                now = now + remaining  # predicted, not re-read -- keeps
                # tests deterministic with a fake `now` that doesn't
                # auto-advance just because `sleep` was called.
        self._last_call = now
