"""Deterministic run_id generation for idempotent pipeline runs."""

from __future__ import annotations

import hashlib


def compute_run_id(period: str, source_signature: str) -> str:
    """Hash (period + source signature) into a stable run_id.

    Same period + same source data signature always produces the same
    run_id, so a completed run is never accidentally reprocessed.
    """
    raw = f"{period}:{source_signature}".encode("utf-8")
    return hashlib.sha256(raw).hexdigest()[:16]
