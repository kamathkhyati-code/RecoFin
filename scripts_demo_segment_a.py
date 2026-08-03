"""A20: Demo prep (data side) -- rehearse the data-side segment of the
live demo against sample_data/, and capture final data metrics.

Run this live during the demo:  python scripts_demo_segment_a.py

Uses the exact same sample_data/book.csv + sample_data/bank_source.csv
pair already verified end-to-end in A18's docs and A19's bug-bash dry
run (book=4 clean rows, bank=3 clean rows after 2 bad rows rejected at
ingestion, 3 matched, 1 unmatched). Also writes
docs/data_agents/DEMO_SEGMENT_A_METRICS.md with a captured snapshot of
this exact run's metrics, so there's a record beyond the live terminal
output -- captured from a real run, not hand-written after the fact.
"""
from __future__ import annotations

from pathlib import Path

from datagents.schemas import SourceConfig, SourceType
from recon_platform.graph.build import build_graph

BANK_FIELD_MAP = {"transaction_id": "txn_id", "value_date": "date", "ccy": "currency"}


def run_demo_segment_a() -> dict:
    graph = build_graph()
    result = graph.invoke({
        "run_id": "demo-segment-a",
        "period": "2026-01",
        "messages": [],
        "issues": [],
        "book_source_configs": [
            SourceConfig(name="book", source_type=SourceType.CSV, location="sample_data/book.csv"),
        ],
        "bank_source_configs": [
            SourceConfig(
                name="bank", source_type=SourceType.CSV, location="sample_data/bank_source.csv",
                options={"field_map": BANK_FIELD_MAP},
            ),
        ],
    })
    return result


def _render(result: dict) -> str:
    lines = []

    def emit(line: str = "") -> None:
        lines.append(line)

    emit("=== A20 Demo Segment A: Data Side ===")
    emit()
    emit(f"Book transactions ingested:   {len(result['book_transactions'])}")
    emit(f"Bank transactions ingested:   {len(result['source_transactions'])}")
    emit(f"Issues (bad rows rejected):   {len(result['issues'])}")
    emit()
    emit("-- Ingestion metrics per source --")
    for m in result["ingestion_metrics"]:
        emit(
            f"  {m['source_name']:6s} type={m['source_type']:4s} "
            f"rows_in={m['rows_in']:>2} rows_out={m['rows_out']:>2} "
            f"issues_out={m['issues_out']} retries={m['retry_attempts']} "
            f"duration_ms={m['duration_ms']:.2f} status={m['status']}"
        )
    emit()
    emit(f"Matched:                      {result['matched_count']}")
    emit(f"Unmatched:                    {result['unmatched_count']}")
    emit(f"Match rate:                   {result['report'].match_rate:.0%}")
    emit(f"Close ready:                  {result['close_ready']}")
    emit()
    emit("Issues detail:")
    for issue in result["issues"]:
        emit(f"  [{issue.severity}] {issue.source}: {issue.message}")

    return "\n".join(lines)


def main() -> None:
    result = run_demo_segment_a()
    rendered = _render(result)
    print(rendered)

    out_path = Path("docs/data_agents/DEMO_SEGMENT_A_METRICS.md")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(
        "# A20: Demo Segment A -- Captured Data Metrics\n\n"
        "Captured from a live run of `scripts_demo_segment_a.py` against "
        "`sample_data/book.csv` and `sample_data/bank_source.csv`.\n\n"
        "```\n" + rendered + "\n```\n",
        encoding="utf-8",
    )
    print(f"\nMetrics captured to {out_path}")


if __name__ == "__main__":
    main()
