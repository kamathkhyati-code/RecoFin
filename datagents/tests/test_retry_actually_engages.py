"""Fix #2: retry actually engages on a real transient failure.

Flagged in A16, documented as a known limitation in A18, and left
unfixed through A19 (got sidetracked by two bigger findings from
diffing against Khyati's branch). None of the three real source tools
ever raised FetchError -- they all caught their own failures into a
graceful IssueRecord, so with_retry (used by ingestion_agent._run_source)
never actually retried anything real; only tests that monkeypatched a
tool to raise FetchError directly ever exercised the retry path.

Fixed in ingestion_agent._call_tool: a transient-looking total failure
(timeout, connection, unreachable, refused, reset) is now raised as
FetchError so the retry loop genuinely engages. A permanent failure
(missing file, malformed row/shape) still degrades immediately with no
pointless retries -- proven here with a REAL flaky HTTP server, not a
monkeypatched fake, so this actually exercises api_fetch_tool's real
httpx timeout path end to end.
"""
from __future__ import annotations

import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from datagents.agents.ingestion_agent import ingest_sources, ingest_sources_with_metrics
from datagents.schemas import SourceConfig, SourceType


def _serve_flaky(fail_times: int, slow_seconds: float = 2.0):
    """A real HTTP server that hangs (triggering a client-side timeout)
    for the first `fail_times` requests, then responds normally."""
    state = {"calls": 0}

    class FlakyHandler(BaseHTTPRequestHandler):
        def do_GET(self):
            state["calls"] += 1
            if state["calls"] <= fail_times:
                time.sleep(slow_seconds)
            self.send_response(200)
            self.end_headers()
            self.wfile.write(
                b'[{"txn_id":"T1","date":"2026-01-01","amount":"10.00",'
                b'"currency":"USD","counterparty":"ACME","reference":"INV-1"}]'
            )

        def log_message(self, *a):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), FlakyHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, state


def test_transient_timeout_actually_retries_and_recovers():
    """A real client-side timeout on the first 2 attempts, then a real
    successful response on the 3rd -- proves the retry loop genuinely
    re-invokes the real api_fetch_tool call, not just that with_retry
    works in isolation against a synthetic FetchError-raising fake.
    """
    server, state = _serve_flaky(fail_times=2, slow_seconds=2.0)
    host, port = server.server_address
    try:
        cfg = SourceConfig(
            name="flaky", source_type=SourceType.API, location=f"http://{host}:{port}/",
            options={"timeout": 0.3, "retries": 3, "retry_base_delay": 0},
        )
        merged, spans = ingest_sources_with_metrics([cfg])
    finally:
        server.shutdown()

    assert state["calls"] == 3
    assert len(merged.transactions) == 1
    assert merged.transactions[0].txn_id == "T1"
    assert spans[0].retry_attempts == 3
    assert spans[0].status == "ok"


def test_transient_failure_that_never_recovers_still_degrades_gracefully():
    """If every attempt is transient, retries exhaust and this still
    degrades to a recorded issue instead of crashing the run -- same
    contract as before this fix, just now actually exercised via retries
    instead of succeeding trivially on the first (never-retried) attempt.
    """
    server, state = _serve_flaky(fail_times=999, slow_seconds=2.0)
    host, port = server.server_address
    try:
        cfg = SourceConfig(
            name="always_down", source_type=SourceType.API, location=f"http://{host}:{port}/",
            options={"timeout": 0.3, "retries": 3, "retry_base_delay": 0},
        )
        merged, spans = ingest_sources_with_metrics([cfg])
    finally:
        server.shutdown()

    assert state["calls"] == 3
    assert merged.transactions == []
    assert len(merged.issues) == 1
    assert merged.issues[0].severity == "error"
    assert spans[0].retry_attempts == 3
    assert spans[0].status == "error"


def test_permanent_file_not_found_does_not_retry_pointlessly():
    """A missing file is not transient -- retrying it forever would never
    help, so this must complete in a single attempt, not 3."""
    cfg = SourceConfig(name="missing", source_type=SourceType.CSV, location="/no/such/file.csv")

    merged, spans = ingest_sources_with_metrics([cfg])

    assert merged.transactions == []
    assert len(merged.issues) == 1
    assert "File not found" in merged.issues[0].message
    assert spans[0].retry_attempts == 1
    assert spans[0].status == "ok"


def test_ingest_sources_plain_function_also_gets_the_retry_fix():
    """ingest_sources (the metrics-free variant, used by callers that
    predate A13) must benefit from the same fix, not just
    ingest_sources_with_metrics."""
    server, state = _serve_flaky(fail_times=1, slow_seconds=2.0)
    host, port = server.server_address
    try:
        cfg = SourceConfig(
            name="flaky2", source_type=SourceType.API, location=f"http://{host}:{port}/",
            options={"timeout": 0.3, "retries": 3, "retry_base_delay": 0},
        )
        merged = ingest_sources([cfg])
    finally:
        server.shutdown()

    assert state["calls"] == 2
    assert len(merged.transactions) == 1
