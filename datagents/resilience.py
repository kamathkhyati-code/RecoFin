"""Ingestion resilience (A5) — retry a transient source fetch with backoff.

Source fetches can fail transiently (network blips, a momentarily unavailable
API/SFTP). `with_retry` re-runs the callable on `FetchError` with exponential
backoff, emits a structured log line per attempt, and re-raises the last error
once attempts are exhausted. `sleep` is injectable so tests run instantly.
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
) -> T:
    """Call `fn`, retrying on FetchError with exponential backoff.

    Makes up to `retries` total attempts. The delay before retry n (1-indexed)
    is base_delay * 2 ** (n - 1). Re-raises the last FetchError if every
    attempt fails; non-FetchError exceptions propagate immediately (not retried).
    """
    attempt = 0
    while True:
        try:
            return fn()
        except FetchError as exc:
            attempt += 1
            if attempt >= retries:
                logger.error(
                    "fetch_retry_exhausted",
                    extra={"attempt": attempt, "retries": retries, "error": str(exc)},
                )
                raise
            delay = base_delay * (2 ** (attempt - 1))
            logger.warning(
                "fetch_retry",
                extra={"attempt": attempt, "delay": delay, "error": str(exc)},
            )
            sleep(delay)
