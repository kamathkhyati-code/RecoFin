"""Report writer: emits eval results as JSON and Markdown."""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone


def write_report(metrics: dict, output_dir: str, run_label: str = "eval") -> tuple[str, str]:
    """Write metrics to <output_dir>/<run_label>.json and .md. Returns (json_path, md_path)."""
    os.makedirs(output_dir, exist_ok=True)

    json_path = os.path.join(output_dir, f"{run_label}.json")
    md_path = os.path.join(output_dir, f"{run_label}.md")

    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "metrics": metrics,
    }
    with open(json_path, "w") as f:
        json.dump(payload, f, indent=2)

    lines = [f"# Eval Report: {run_label}", "", f"Generated: {payload['generated_at']}", ""]
    for key, value in metrics.items():
        if isinstance(value, dict):
            lines.append(f"## {key}")
            for sub_key, sub_value in value.items():
                if isinstance(sub_value, float):
                    lines.append(f"- **{sub_key}**: {sub_value:.4f}")
                else:
                    lines.append(f"- **{sub_key}**: {sub_value}")
        else:
            if isinstance(value, float):
                lines.append(f"- **{key}**: {value:.4f}")
            else:
                lines.append(f"- **{key}**: {value}")
    with open(md_path, "w") as f:
        f.write("\n".join(lines) + "\n")

    return json_path, md_path
