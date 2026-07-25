# Runbook

Every command below was actually run against the current codebase while
writing this doc, not just written to look plausible. If one stops working,
that's a real regression -- file it, don't just edit this doc to match.

## Setup

```bash
git clone <repo-url> RecoFin
cd RecoFin
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
```

Real LLM calls (`GroqLLMGateway`) need `GROQ_API_KEY` in your environment or
a local `.env` (gitignored, never commit it). Everything in this runbook
works without one -- `MockLLMGateway` and the deterministic-only paths don't
need a real key.

## Run the tests

```bash
pytest datagents/ reasoning/ tests/ -v   # full suite
ruff check .                              # lint
```

CI (`.github/workflows/ci.yml`) runs exactly this on every push/PR.

## Run a real pipeline end to end

```python
from pathlib import Path
from datagents.schemas import SourceConfig, SourceType
from recon_platform.graph.checkpointer import get_checkpointer, run_pipeline

SAMPLE = Path("sample_data")
FIELD_MAP = {"transaction_id": "txn_id", "value_date": "date", "ccy": "currency"}

with get_checkpointer("checkpoints.db") as cp:
    initial_state = {
        "run_id": "my-run-1",
        "period": "2026-01",
        "messages": [], "issues": [],
        "book_source_configs": [
            SourceConfig(name="book", source_type=SourceType.CSV, location=str(SAMPLE / "book.csv")),
        ],
        "bank_source_configs": [
            SourceConfig(
                name="bank", source_type=SourceType.CSV,
                location=str(SAMPLE / "bank_source.csv"), options={"field_map": FIELD_MAP},
            ),
        ],
    }
    result = run_pipeline("2026-01", "my-source-signature", cp, initial_state=initial_state)
    report = result["state"]["report"]
    print(report.matched_count, report.unmatched_count, report.close_ready)
    # -> 3 1 False   (on the golden sample data)
```

Calling `run_pipeline` again with the same `(period, source_signature)`
skips entirely (`result["skipped"] is True`) if the run already completed.

## Resume an interrupted run

If a run was killed mid-flight (process died, deploy restarted, whatever),
just call `run_pipeline` again with the **same** `(period,
source_signature)` and the **same** checkpointer db file. It resumes from
the last checkpoint automatically -- nothing already completed re-runs. See
`tests/test_chaos.py` for the exact mechanics and the bug this used to have.

## Review and resolve an escalated exception (HITL)

```python
from recon_platform.hitl.review_queue import review_queue, pending_for_run
from reasoning.agents.exception_escalation import resolve_exception

pending_for_run("my-run-1")          # this run's still-open exceptions
review_queue.pending()               # every run's still-open exceptions

# result["state"]["exceptions"] holds the ExceptionRecord objects from the run above
for exc in result["state"]["exceptions"]:
    resolve_exception(exc, run_id="my-run-1", analyst_note="Confirmed with bank.")
```

A run can't be closed while it has pending exceptions --
`recon_platform.hitl.close_gate.close_period(report)` raises
`PrematureCloseError` until they're resolved.

## Approve a mined rule suggestion

Each completed run (with no pending exceptions) mines recurring
tolerance/fuzzy/exception patterns into the shared `RuleStore`:

```python
from reasoning.rule_store import rule_store

rule_store.pending()                 # suggestions awaiting a decision
rule_store.approve(item_id=1)        # approve one (get the id from .pending())
```

An approved suggestion is picked up automatically by the **next** run's
matching step -- no extra plumbing, no restart needed.

## Generate a baseline metrics report

```python
from recon_platform.eval.baseline import run_baseline

json_path, md_path = run_baseline(initial_state, output_dir="reports/")
```

Captures auto-match rate, exception count, latency, and token cost from a
real graph run, writes versioned JSON+MD (one file pair per `run_id`, never
overwritten).

## Regenerate the architecture diagram

```bash
python scripts_render_graph.py
```

Writes `docs/graph/recon_graph.png` directly from the live compiled graph.
Run this whenever `recon_platform/graph/build.py`'s node/edge structure
changes, so the diagram in `ARCHITECTURE.md` can't silently drift from the
code.

## Troubleshooting

- **A resumed run seems to re-process everything from scratch.** This was a
  real bug (fixed in C16) -- if you see it again, check whether whatever's
  calling `graph.invoke` is passing a fresh state object instead of `None`
  for an already-interrupted thread.
- **A node's output seems to vanish.** Check `recon_platform/state.py`'s
  `ReconState` -- if the key isn't declared there, LangGraph silently drops
  it. This has bitten this repo twice already (see `ARCHITECTURE.md`'s
  Known gaps).
- **Tests are slow or hang.** Almost certainly an iCloud-synced (or similar
  cloud-synced) working directory turning local file reads into network
  fetches. Move the repo to a plain local directory.
