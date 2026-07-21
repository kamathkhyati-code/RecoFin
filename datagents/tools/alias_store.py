"""Alias store (A9) - persistent cache of LLM-resolved entity-name aliases.
Backs entity_alias_tool so a name resolved once (via LLM) is remembered on
disk; a second run reads the cache instead of calling the LLM again, keeping
normalization deterministic and idempotent across runs.
"""
from __future__ import annotations
import json
from pathlib import Path


class AliasStore:
    """A simple on-disk key -> canonical-name cache, keyed by UPPER name."""

    def __init__(self, path: str | Path = "alias_cache.json") -> None:
        self.path = Path(path)
        self._data: dict[str, str] = {}
        if self.path.exists():
            self._data = json.loads(self.path.read_text(encoding="utf-8"))

    def get(self, key: str) -> str | None:
        """Return the cached canonical name for `key`, or None if not cached."""
        return self._data.get(key)

    def set(self, key: str, value: str) -> None:
        """Cache `key` -> `value` and persist to disk immediately."""
        self._data[key] = value
        self.path.write_text(json.dumps(self._data, indent=2), encoding="utf-8")
