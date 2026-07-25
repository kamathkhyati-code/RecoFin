"""A16: harden ingestion -- timeouts, rate limits, partial-batch handling,
secrets via env only.

Timeout-injected graceful degrade is proven with REAL injected timeouts
(a slow HTTP server, a fake SFTP client that raises socket.timeout), not
just trusting that the exception classes line up -- confirmed manually
before writing this, then locked in as regression tests here.
"""
from __future__ import annotations

import re
import socket
import threading
import time
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

import pytest

from datagents.agents.ingestion_agent import _resolve_sftp_credentials, ingest_sources
from datagents.resilience import RateLimiter
from datagents.schemas import SourceConfig, SourceType
from datagents.tools.api_fetch_tool import api_fetch_tool
from datagents.tools.csv_read_tool import csv_read_tool
from datagents.tools.sftp_fetch_tool import sftp_fetch_tool

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent


# ---- Timeout -> graceful degrade ----


def _serve_slow(delay_seconds: float):
    class SlowHandler(BaseHTTPRequestHandler):
        def do_GET(self):
            time.sleep(delay_seconds)
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b"[]")

        def log_message(self, *a):
            pass

    server = HTTPServer(("127.0.0.1", 0), SlowHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server


def test_api_timeout_injected_degrades_gracefully_not_a_crash():
    server = _serve_slow(delay_seconds=1.0)
    host, port = server.server_address
    try:
        result = api_fetch_tool(f"http://{host}:{port}/", source_name="slow_api", timeout=0.2)
    finally:
        server.shutdown()

    assert result.transactions == []
    assert len(result.issues) == 1
    assert result.issues[0].severity == "error"
    assert "timed out" in result.issues[0].message.lower() or "timeout" in result.issues[0].message.lower()


def test_sftp_timeout_injected_degrades_gracefully_not_a_crash(tmp_path):
    class TimeoutSFTPClient:
        def get(self, remote_path, local_path):
            raise socket.timeout("connection timed out")

    result = sftp_fetch_tool(
        host="sftp.example.com", remote_path="/t.csv", source_name="slow_sftp",
        local_dir=str(tmp_path), sftp_client=TimeoutSFTPClient(),
    )

    assert result.transactions == []
    assert len(result.issues) == 1
    assert result.issues[0].severity == "error"
    assert "timed out" in result.issues[0].message.lower()


# ---- Rate limiting ----


def test_rate_limiter_enforces_minimum_interval_between_calls():
    fake_time = {"t": 0.0}
    sleeps: list[float] = []

    def fake_sleep(seconds):
        sleeps.append(seconds)
        fake_time["t"] += seconds

    def fake_now():
        return fake_time["t"]

    limiter = RateLimiter(min_interval_seconds=1.0, sleep=fake_sleep, now=fake_now)

    limiter.wait()  # first call: nothing elapsed yet, no sleep needed
    assert sleeps == []

    fake_time["t"] += 0.3  # only 0.3s passed before the next call
    limiter.wait()
    assert sleeps == [pytest.approx(0.7)]  # had to wait the remaining 0.7s

    fake_time["t"] += 2.0  # plenty of time passed
    limiter.wait()
    assert sleeps == [pytest.approx(0.7)]  # no additional sleep needed


def test_rate_limiter_wired_into_ingest_sources_paces_repeated_calls(tmp_path):
    calls = {"n": 0}
    sleeps: list[float] = []

    csv_file = tmp_path / "t.csv"
    csv_file.write_text("txn_id,date,amount,currency,counterparty,reference\nT1,2026-01-01,10.00,USD,ACME,INV-1\n")

    fake_time = {"t": 0.0}

    def fake_sleep(seconds):
        sleeps.append(seconds)
        fake_time["t"] += seconds

    def fake_now():
        calls["n"] += 1
        return fake_time["t"]

    limiter = RateLimiter(min_interval_seconds=5.0, sleep=fake_sleep, now=fake_now)
    configs = [
        SourceConfig(name="a", source_type=SourceType.CSV, location=str(csv_file)),
        SourceConfig(name="b", source_type=SourceType.CSV, location=str(csv_file)),
    ]

    ingest_sources(configs, rate_limiter=limiter)

    # Second source's call had to wait ~5s since the first call happened at t=0.
    assert sleeps == [pytest.approx(5.0)]


def test_no_rate_limiter_means_no_pacing_at_all_by_default(tmp_path):
    """Default behavior (no rate_limiter passed) must be completely
    unaffected -- every existing caller/test relies on this."""
    csv_file = tmp_path / "t.csv"
    csv_file.write_text("txn_id,date,amount,currency,counterparty,reference\nT1,2026-01-01,10.00,USD,ACME,INV-1\n")
    configs = [SourceConfig(name="a", source_type=SourceType.CSV, location=str(csv_file))]

    start = time.monotonic()
    ingest_sources(configs)
    elapsed = time.monotonic() - start

    assert elapsed < 1.0  # no artificial pacing introduced


# ---- Partial-batch handling ----


def test_csv_partial_batch_bad_row_in_the_middle_does_not_stop_the_rest(tmp_path):
    f = tmp_path / "t.csv"
    f.write_text(
        "txn_id,date,amount,currency,counterparty,reference\n"
        "T1,2026-01-01,10.00,USD,ACME,INV-1\n"
        "T2,2026-01-02,20.00,USD,GLOBEX,INV-2\n"
        "T3,not-a-date,30.00,USD,INITECH,INV-3\n"
        "T4,2026-01-04,40.00,USD,UMBRELLA,INV-4\n"
        "T5,2026-01-05,50.00,USD,ACME,INV-5\n"
    )

    result = csv_read_tool(str(f), source_name="batch")

    assert result.rows_read == 5
    assert {t.txn_id for t in result.transactions} == {"T1", "T2", "T4", "T5"}
    assert len(result.issues) == 1
    assert result.issues[0].row_ref == "3"


# ---- Secrets via env only ----


def test_sftp_credentials_resolve_from_env_via_credentials_ref(monkeypatch):
    monkeypatch.setenv("TEST_SFTP_CREDS", "realuser:realpass")
    config = SourceConfig(
        name="bank_sftp", source_type=SourceType.SFTP, location="/t.csv",
        credentials_ref="TEST_SFTP_CREDS",
    )
    username, password = _resolve_sftp_credentials(config, config.options or {})
    assert username == "realuser"
    assert password == "realpass"


def test_sftp_credentials_fall_back_to_options_when_no_credentials_ref():
    config = SourceConfig(
        name="bank_sftp", source_type=SourceType.SFTP, location="/t.csv",
        options={"username": "devuser", "password": "devpass"},
    )
    username, password = _resolve_sftp_credentials(config, config.options)
    assert username == "devuser"
    assert password == "devpass"


_SUSPICIOUS_PATTERN = re.compile(
    r'(password|passwd|api_key|apikey|secret|access_token)\s*=\s*["\'](?!["\']\s*$)[^"\']{4,}["\']',
    re.IGNORECASE,
)
_ALLOWED_FALSE_POSITIVE_SUBSTRINGS = (
    'password: str = ""',
)


def test_no_hardcoded_credentials_in_source():
    """Automated secret scan: fails if any datagents/reasoning/recon_platform
    source file contains what looks like a literal hardcoded credential.
    Meant to be the repeatable check behind "secret scan finds no hardcoded
    credentials", not a one-off manual grep.
    """
    offenders = []
    for pkg in ("datagents", "reasoning", "recon_platform"):
        pkg_dir = _REPO_ROOT / pkg
        for path in pkg_dir.rglob("*.py"):
            if "test" in path.parts or "__pycache__" in path.parts:
                continue
            text = path.read_text(encoding="utf-8", errors="ignore")
            for match in _SUSPICIOUS_PATTERN.finditer(text):
                line = match.group(0)
                if any(allowed in line for allowed in _ALLOWED_FALSE_POSITIVE_SUBSTRINGS):
                    continue
                offenders.append(f"{path.relative_to(_REPO_ROOT)}: {line}")

    assert offenders == [], "Possible hardcoded credential(s):\n" + "\n".join(offenders)
