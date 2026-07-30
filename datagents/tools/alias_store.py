"""Alias store (A9) - persistent cache of LLM-resolved entity-name aliases.

Backs entity_alias_tool so a name resolved once (via LLM) is remembered on
disk; a second run reads the cache instead of calling the LLM again, keeping
normalization deterministic and idempotent across runs.

A17 (ingestion performance): set() used to rewrite the *entire* cache file
(json.dumps of the whole dict) on every single call -- durable (crash-safe
after each resolution) but O(n) I/O per call, O(n^2) total across a batch
with n unresolved names. At 10k rows where every counterparty was a fresh
cache miss, this took ~30s and would only get worse at 50k/100k rows.

Fixed by switching the on-disk format to an append-only NDJSON log: each
set() appends one line (O(1) I/O), so a full batch of n misses costs O(n)
total instead of O(n^2), while keeping the exact same durability guarantee
(every resolution is flushed to disk immediately, not batched/buffered).
Loading replays the log and keeps the last value per key. For backward
compatibility, if an existing cache file is the old single-JSON-object
format, it's detected (the first line doesn't look like an NDJSON record),
read once, and migrated: rewritten as an NDJSON log on the spot so
subsequent set() calls are cheap.
"""
from __future__ import annotations

import json
from pathlib import Path


class AliasStore:
    """A simple on-disk key -> canonical-name cache, keyed by UPPER name.

    Storage format is an append-only NDJSON log (one {"key": ..., "value":
    ...} object per line); the last line for a given key wins. This keeps
    every set() an O(1) append instead of an O(n) full-file rewrite.
    """

    def __init__(self, path: str | Path = "alias_cache.json") -> None:
        self.path = Path(path)
        self._data: dict[str, str] = {}
        if self.path.exists():
            self._load()

    def _load(self) -> None:
        text = self.path.read_text(encoding="utf-8")
        stripped = text.strip()
        if not stripped:
            return

        lines = [ln.strip() for ln in stripped.splitlines() if ln.strip()]
        first_record = self._try_parse_ndjson_record(lines[0])
        if first_record is None:
            # Old format: a single JSON object (possibly pretty-printed
            # across multiple lines) holding the whole cache.
            self._data = json.loads(stripped)
            self._migrate_to_ndjson()
            return

        # NDJSON: one {"key": ..., "value": ...} record per line, last wins.
        for line in lines:
            record = self._try_parse_ndjson_record(line)
            if record is not None:
                self._data[record["key"]] = record["value"]

    @staticmethod
    def _try_parse_ndjson_record(line: str) -> dict | None:
        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            return None
        if isinstance(obj, dict) and set(obj.keys()) == {"key", "value"}:
            return obj
        return None

    def _migrate_to_ndjson(self) -> None:
        """Rewrite an old single-JSON-object cache as an NDJSON log once,
        so future set() calls append instead of rewriting the whole file."""
        lines = [json.dumps({"key": k, "value": v}) for k, v in self._data.items()]
        self.path.write_text("\n".join(lines) + ("\n" if lines else ""), encoding="utf-8")

    def get(self, key: str) -> str | None:
        """Return the cached canonical name for `key`, or None if not cached."""
        return self._data.get(key)

    def set(self, key: str, value: str) -> None:
        """Cache `key` -> `value` and durably append it to disk (O(1))."""
        self._data[key] = value
        with self.path.open("a", encoding="utf-8") as f:
            f.write(json.dumps({"key": key, "value": value}) + "\n")
