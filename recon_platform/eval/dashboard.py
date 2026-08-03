"""C20: eval dashboard -- aggregate one or more baseline/eval JSON
reports (C13's run_baseline, C9's run_eval) into a single presentable
view for the demo, rather than making someone open several scattered
JSON files by hand.
"""

from __future__ import annotations

import json
import os
from typing import Any


def _load_reports(json_paths: list[str]) -> list[dict[str, Any]]:
    reports = []
    for path in json_paths:
        with open(path) as f:
            reports.append(json.load(f))
    return reports


def render_dashboard(json_paths: list[str], output_path: str) -> str:
    """Aggregate baseline/eval JSON reports into one markdown dashboard.

    Each input file is whatever write_report() (recon_platform/eval/
    report.py) already wrote -- this doesn't recompute anything, it just
    presents what's already been measured in one place.
    """
    reports = _load_reports(json_paths)

    lines = ["# Eval Dashboard", "", f"{len(reports)} run(s) aggregated.", ""]
    lines.append("| run_id | matched | unmatched | exceptions | auto_match_rate | close_ready | latency_ms | tokens |")
    lines.append("|---|---|---|---|---|---|---|---|")

    for report in reports:
        m = report.get("metrics", {})
        lines.append(
            "| {run_id} | {matched} | {unmatched} | {exceptions} | {rate:.1%} | {close} | {latency:.1f} | {tokens} |".format(
                run_id=m.get("run_id", "?"),
                matched=m.get("matched_count", "?"),
                unmatched=m.get("unmatched_count", "?"),
                exceptions=m.get("exception_count", "?"),
                rate=m.get("auto_match_rate", 0.0),
                close=m.get("close_ready", "?"),
                latency=m.get("latency_ms", 0.0),
                tokens=m.get("total_tokens", "?"),
            )
        )

    if reports:
        rates = [r["metrics"].get("auto_match_rate", 0.0) for r in reports if "metrics" in r]
        latencies = [r["metrics"].get("latency_ms", 0.0) for r in reports if "metrics" in r]
        lines += [
            "",
            "## Summary",
            "",
            f"- Average auto-match rate: {sum(rates) / len(rates):.1%}" if rates else "",
            f"- Average latency: {sum(latencies) / len(latencies):.1f} ms" if latencies else "",
        ]

    content = "\n".join(line for line in lines if line is not None)

    os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)
    with open(output_path, "w") as f:
        f.write(content + "\n")

    return output_path
