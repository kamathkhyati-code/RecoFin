"""Generate the B15 matching eval + ablation report.

Run as: python -m reasoning.evals.generate_match_eval_report
Writes reasoning/evals/match_eval_report.md with the ablation table.
"""
from __future__ import annotations

from pathlib import Path

from reasoning.evals.golden_matching_dataset import build_golden_dataset
from reasoning.evals.match_eval import run_ablation

_REPORT_PATH = Path(__file__).parent / "match_eval_report.md"


def build_report() -> str:
    book, source, true_pairs, unm_book, unm_source = build_golden_dataset()
    rows = run_ablation(book, source, true_pairs, seed_pair_id=("B-SM1", "S-SM1"))

    lines = [
        "# Matching Eval + Ablation Report (B15)",
        "",
        f"Golden dataset: {len(book)} book txns, {len(source)} source txns, "
        f"{len(true_pairs)} true matches, {len(unm_book)} book-only and "
        f"{len(unm_source)} source-only leftovers.",
        "",
        "| Layer | Matched | Precision | Recall | Auto-match rate | Hallucination rate |",
        "|---|---|---|---|---|---|",
    ]
    for row in rows:
        lines.append(
            f"| {row['layer']} | {row['matched_count']} | {row['precision']} | "
            f"{row['recall']} | {row['auto_match_rate']} | {row['hallucination_rate']} |"
        )
    lines.append("")
    lines.append(
        "Reading the table: deterministic-only misses the two semantic-only "
        "pairs (SM1/SM2), so recall is below 1.0. Adding the LLM layer "
        "recovers both, taking recall to 1.0 with no precision loss. Adding "
        "match memory (RAG) does not change which pairs are matched -- it "
        "only recalibrates confidence for the pair with prior history "
        "(B-SM1/S-SM1, pre-seeded here), raising the auto-match rate "
        "without touching precision or recall."
    )
    return "\n".join(lines)


def main() -> None:
    report = build_report()
    _REPORT_PATH.write_text(report, encoding="utf-8")
    print(report)


if __name__ == "__main__":
    main()
