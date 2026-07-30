"""A17: ingestion performance -- 10k-row batch, memory profile.

Day_Plan A17: "Batch/stream a 10k-row sample; memory profile." Acceptance:
"10k rows ingest+normalize under target time; memory stable (no leak)."

No numeric target time is given in the spec, so this file states the
targets it enforces explicitly (see _INGEST_TARGET_SECONDS /
_NORMALIZE_TARGET_SECONDS below) rather than leaving it implicit --
picked with generous headroom over what was actually measured on the dev
machine (~0.08s ingest, ~0.2s worst-case normalize for 10k rows), so this
stays robust on a slower CI box while still catching a real regression.

Investigating this task surfaced a real O(n^2) bug: AliasStore.set()
rewrote the *entire* cache file on every call. With 10k rows where every
counterparty was a fresh cache miss (the realistic worst case for a
first-ever run against a new source), that took ~30s and would only get
worse at 50k/100k rows -- comfortably blowing any reasonable "under
target time" bar. Fixed in datagents/tools/alias_store.py by switching to
an append-only NDJSON log (O(1) per set() instead of O(n)); the fix and
its regression test live here since it was found by, and is exercised by,
this perf test.
"""
from __future__ import annotations

import gc
import random
import time
import tracemalloc
from datetime import date, timedelta
from decimal import Decimal

from datagents.agents.normalization_agent import normalize_transactions
from datagents.schemas import Currency, SourceType, Transaction
from datagents.tools.alias_store import AliasStore
from datagents.tools.csv_read_tool import csv_read_tool
from recon_platform.gateway.llm_gateway import MockLLMGateway

_ROWS = 10_000
_INGEST_TARGET_SECONDS = 2.0
_NORMALIZE_TARGET_SECONDS = 5.0


def _write_10k_csv(path) -> None:
    rng = random.Random(42)
    base = date(2026, 1, 1)
    lines = ["txn_id,date,amount,currency,counterparty,reference"]
    for i in range(_ROWS):
        lines.append(
            f"T{i},{(base + timedelta(days=i % 300)).isoformat()},"
            f"{rng.uniform(1, 10000):.2f},"
            f"{rng.choice(['USD', 'EUR', 'GBP'])},"
            f"Counterparty{i % 500},INV-{i}"
        )
    path.write_text("\n".join(lines) + "\n")


def test_10k_row_csv_ingest_completes_under_target_time_no_bad_rows(tmp_path):
    csv_path = tmp_path / "perf10k.csv"
    _write_10k_csv(csv_path)

    t0 = time.perf_counter()
    result = csv_read_tool(str(csv_path), source_name="perf")
    elapsed = time.perf_counter() - t0

    assert result.rows_read == _ROWS
    assert len(result.transactions) == _ROWS
    assert result.issues == []
    assert elapsed < _INGEST_TARGET_SECONDS, (
        f"10k-row ingest took {elapsed:.2f}s, target is {_INGEST_TARGET_SECONDS}s"
    )


def test_10k_row_normalize_worst_case_all_cache_misses_under_target_time(tmp_path):
    """Worst case for normalization: every counterparty is a first-time
    cache miss (a brand-new source on its first run) -- this is exactly
    the scenario that exposed the AliasStore O(n^2) bug.
    """
    txns = [
        Transaction(
            txn_id=f"T{i}",
            date=date(2026, 1, 1),
            amount=Decimal("10.00"),
            currency=Currency.USD,
            counterparty=f"NeverSeenBefore{i}",
            reference=f"R{i}",
            source=SourceType.CSV,
        )
        for i in range(_ROWS)
    ]
    store = AliasStore(tmp_path / "alias_cache.json")
    gateway = MockLLMGateway("RESOLVED")

    t0 = time.perf_counter()
    normalized = normalize_transactions(txns, gateway=gateway, store=store)
    elapsed = time.perf_counter() - t0

    assert len(normalized) == _ROWS
    assert elapsed < _NORMALIZE_TARGET_SECONDS, (
        f"10k-row worst-case normalize took {elapsed:.2f}s, "
        f"target is {_NORMALIZE_TARGET_SECONDS}s "
        "(if this regresses toward ~30s, AliasStore.set() is back to "
        "rewriting the whole cache file per call)"
    )


def test_repeated_10k_ingest_normalize_runs_do_not_leak_memory(tmp_path):
    """Run the full ingest+normalize pipeline 3 times back-to-back and
    confirm peak memory in the 3rd run isn't materially higher than the
    1st -- a real leak would show monotonically growing peak usage.
    """
    csv_path = tmp_path / "perf10k.csv"
    _write_10k_csv(csv_path)

    peaks = []
    for i in range(3):
        store = AliasStore(tmp_path / f"alias_cache_{i}.json")
        gateway = MockLLMGateway("RESOLVED")

        gc.collect()
        tracemalloc.start()
        result = csv_read_tool(str(csv_path), source_name="perf")
        normalize_transactions(result.transactions, gateway=gateway, store=store)
        _current, peak = tracemalloc.get_traced_memory()
        tracemalloc.stop()
        peaks.append(peak)

    # Allow generous variance run-to-run, but the 3rd run's peak must not
    # be meaningfully larger than the 1st -- that would indicate something
    # is accumulating across runs rather than being released.
    assert peaks[-1] < peaks[0] * 1.5, f"peak memory grew across repeated runs: {peaks}"


def test_repeated_10k_ingest_normalize_runs_do_not_leak_memory(tmp_path):
    """Run the full ingest+normalize pipeline 3 times back-to-back and
    confirm peak memory in the 3rd run isn't materially higher than the
    1st -- a real leak would show monotonically growing peak usage.
    """
    csv_path = tmp_path / "perf10k.csv"
    _write_10k_csv(csv_path)

    peaks = []
    for i in range(3):
        store = AliasStore(tmp_path / f"alias_cache_{i}.json")
        gateway = MockLLMGateway("RESOLVED")

        gc.collect()
        tracemalloc.start()
        result = csv_read_tool(str(csv_path), source_name="perf")
        normalize_transactions(result.transactions, gateway=gateway, store=store)
        _current, peak = tracemalloc.get_traced_memory()
        tracemalloc.stop()
        peaks.append(peak)

    # Allow generous variance run-to-run, but the 3rd run's peak must not
    # be meaningfully larger than the 1st -- that would indicate something
    # is accumulating across runs rather than being released.
    assert peaks[-1] < peaks[0] * 1.5, f"peak memory grew across repeated runs: {peaks}"


def test_alias_store_set_appends_not_rewrites_the_whole_file(tmp_path):
    """Regression test for the A17 fix: each set() call should append a
    bounded amount of data, not rewrite content proportional to the
    store's current size. Verified indirectly by checking the file's
    growth per write stays roughly constant instead of increasing.
    """
    store = AliasStore(tmp_path / "alias_cache.json")
    sizes = []
    for i in range(50):
        store.set(f"KEY{i}", f"VALUE{i}")
        sizes.append(store.path.stat().st_size)

    growth_per_write = [sizes[i] - sizes[i - 1] for i in range(1, len(sizes))]
    # If set() were still rewriting the whole file, growth_per_write would
    # itself keep growing (each rewrite includes all prior entries again
    # on top of the new one). With appends, growth per write is roughly
    # constant (same-length key/value each time).
    assert max(growth_per_write) < min(growth_per_write) * 3


def test_alias_store_migrates_legacy_single_json_object_format(tmp_path):
    """A cache file written by the old format (one big JSON object) must
    still load correctly and get migrated to the new NDJSON format so
    later set() calls are cheap."""
    import json

    path = tmp_path / "alias_cache.json"
    path.write_text(json.dumps({"OLDCO": "OLDCO CANONICAL"}, indent=2), encoding="utf-8")

    store = AliasStore(path)
    assert store.get("OLDCO") == "OLDCO CANONICAL"

    # After load, the file should have been migrated to NDJSON.
    migrated_text = path.read_text(encoding="utf-8")
    record = __import__("json").loads(migrated_text.strip().splitlines()[0])
    assert record == {"key": "OLDCO", "value": "OLDCO CANONICAL"}

    # And a subsequent set() should append, not rewrite.
    size_before = path.stat().st_size
    store.set("NEWCO", "NEWCO CANONICAL")
    size_after = path.stat().st_size
    assert size_after > size_before
    assert store.get("OLDCO") == "OLDCO CANONICAL"
    assert store.get("NEWCO") == "NEWCO CANONICAL"
