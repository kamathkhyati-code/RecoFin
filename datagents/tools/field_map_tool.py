"""Field-map tool (A4) — remaps drifted source column names to canonical keys."""
from __future__ import annotations

from recon_platform.registry import registry


@registry.register(
    "field_map_tool",
    description="Rename drifted source columns to canonical Transaction field names.",
)
def field_map_tool(row: dict, field_map: dict[str, str] | None = None) -> dict:
    """Return a copy of *row* with keys renamed per *field_map* (source_col -> canonical).

    Keys absent from field_map pass through unchanged. No-op when field_map is falsy.
    """
    if not field_map:
        return row
    return {field_map.get(key, key): value for key, value in row.items()}
