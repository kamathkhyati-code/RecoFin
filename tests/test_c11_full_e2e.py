"""C11 (full): first true E2E -- real ingestion through real graph.

Now that A11 landed (recon_platform/graph/build.py's ingestion_node/
validation_node/normalization_node call the real A-agents, not
placeholders), this proves the actual acceptance criteria: "E2E run on
golden data through the real graph produces a ReconReport" starting from
source_configs, not from directly-injected transactions.

tests/test_c11_integration.py's earlier tests still exercise the B-side
matching/exception/consolidation path in isolation (useful for pinpointing
a failure to that layer specifically) -- this file is the actual "first
true E2E".
"""

from __future__ import annotations

from pathlib import Path

from datagents.schemas import SourceConfig, SourceType
from recon_platform.graph.build import build_graph

_SAMPLE_DIR = Path(__file__).resolve().parent.parent / "sample_data"
_FIELD_MAP = {
    "transaction_id": "txn_id",
    "value_date": "date",
    "ccy": "currency",
}


def _golden_state(run_id: str) -> dict:
    return {
        "run_id": run_id,
        "period": "2026-01",
        "messages": [],
        "issues": [],
        "book_source_configs": [
            SourceConfig(
                name="book",
                source_type=SourceType.CSV,
                location=str(_SAMPLE_DIR / "book.csv"),
            ),
        ],
        "bank_source_configs": [
            SourceConfig(
                name="bank",
                source_type=SourceType.CSV,
                location=str(_SAMPLE_DIR / "bank_source.csv"),
                options={"field_map": _FIELD_MAP},
            ),
        ],
    }


def test_full_e2e_real_ingestion_through_real_graph_produces_recon_report():
    graph = build_graph()
    result = graph.invoke(_golden_state("c11-full-e2e-1"))

    report = result["report"]
    assert report.run_id == "c11-full-e2e-1"

    # book.csv: B1-B4, all clean rows.
    # bank_source.csv: S1-S3 clean, S4 has a malformed amount, S5 has an
    # invalid currency (ZZZ) -- both rejected at ingestion, never reach
    # matching. So: B1/S1, B2/S2, B3/S3 match (post-FX-normalization to a
    # common currency); B4 is the one real exception (no counterpart).
    assert report.matched_count == 3
    assert report.unmatched_count == 1
    assert report.exception_count == 1

    role_values = [m.role.value for m in result["messages"]]
    for role in ("supervisor", "ingestion", "validation", "normalization", "matching", "resolution", "consolidation"):
        assert role in role_values


def test_full_e2e_ingestion_issues_survive_to_final_state():
    """The malformed rows (S4, S5) must show up as real issues, not
    silently vanish -- proves issues actually flow ingestion -> validation
    -> gate -> final state instead of one node overwriting another's.
    issue.source is the specific source config name ("bank"), not a
    generic "ingestion" label -- more useful for pinpointing which feed
    a bad row came from."""
    graph = build_graph()
    result = graph.invoke(_golden_state("c11-full-e2e-2"))

    assert len(result["issues"]) >= 2
    row_refs = {issue.row_ref for issue in result["issues"] if issue.row_ref is not None}
    assert row_refs  # the malformed rows are tied to specific rows, not a batch-level failure
