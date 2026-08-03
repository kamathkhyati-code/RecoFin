# Data Agents (Intern A track)

This covers the **data sub-graph**: ingestion -> validation -> normalization.
It is the first stage of the full reconciliation pipeline -- it turns raw
book/bank sources (CSV, API, SFTP) into a clean, validated, currency- and
name-normalized set of `Transaction` objects ready for matching.

Everything here has been run and verified against the real code (not just
described from memory) as of A18.

## Where this fits

The full pipeline (compiled in `recon_platform/graph/build.py`) runs:
ingestion -> validation -> normalization -> matching -> resolution ->
consolidation -> learning. Validation can loop back to ingestion on a bad
batch, and can also escalate a single ambiguous row to human review.

This doc covers the first three nodes -- ingestion, validation,
normalization -- the "data sub-graph." Matching/resolution/consolidation
belong to Intern B/C. A rendered PNG of the entire compiled graph already
exists at `docs/graph/recon_graph.png`. See `sequence_diagram.md` in this
same folder for a diagram scoped to just the data sub-graph.

## Running it standalone (no LangGraph needed)

Use this to develop/test the data agents in isolation.
`datagents/data_subgraph.py` threads ingestion, validation, and
normalization together as plain Python function calls on a dict -- no
LangGraph dependency at all.

```python
from datagents.schemas import SourceConfig, SourceType
from datagents.data_subgraph import run_data_subgraph_by_source

# bank_source.csv has drifted column names -- field_map handles that,
# see "Schema drift" below.
BANK_FIELD_MAP = {"transaction_id": "txn_id", "value_date": "date", "ccy": "currency"}

named_configs = {
    "book": [SourceConfig(name="book", source_type=SourceType.CSV, location="sample_data/book.csv")],
    "bank": [SourceConfig(name="bank", source_type=SourceType.CSV, location="sample_data/bank_source.csv",
                          options={"field_map": BANK_FIELD_MAP})],
}
result = run_data_subgraph_by_source(named_configs)

print(len(result["book_transactions"]))   # -> 4
print(len(result["bank_transactions"]))   # -> 3 (one bad amount, one bad currency)
print(len(result["issues"]))              # -> 2
```

This was actually run against this repo before writing these numbers down.
There is also `run_data_subgraph(state)` (singular) for a simpler case with
one combined source list, matching A10s original spec.

## Running it wired into the full graph

This is what actually runs in production/demo. The three data-agent
functions are wrapped as LangGraph nodes (`ingestion_node`,
`validation_node`, `normalization_node` in `recon_platform/graph/build.py`)
and composed with everyone elses nodes into one compiled `StateGraph`.

```python
from recon_platform.graph.build import build_graph
from datagents.schemas import SourceConfig, SourceType

BANK_FIELD_MAP = {"transaction_id": "txn_id", "value_date": "date", "ccy": "currency"}

graph = build_graph()
result = graph.invoke({
    "run_id": "demo-run",
    "period": "2026-01",
    "messages": [],
    "issues": [],
    "book_source_configs": [
        SourceConfig(name="book", source_type=SourceType.CSV, location="sample_data/book.csv"),
    ],
    "bank_source_configs": [
        SourceConfig(name="bank", source_type=SourceType.CSV, location="sample_data/bank_source.csv",
                     options={"field_map": BANK_FIELD_MAP}),
    ],
})

print(result["matched_count"])       # -> 3
print(result["unmatched_count"])     # -> 1
print(result["close_ready"])         # -> False (one unmatched txn)
```

Important: `book_source_configs`/`bank_source_configs`/`ingestion_metrics`
must be declared in `ReconState` (`recon_platform/state.py`) for this to
work -- LangGraph silently drops any key on the initial state, or any
nodes return value, that isnt declared in the schema. This bit us for real
during A13 -- see the node docstrings in `build.py`.

## Configuring a source: SourceConfig

```python
class SourceConfig(BaseModel):
    name: str
    source_type: SourceType          # CSV / API / SFTP
    location: str                    # file path, URL, or SFTP remote path
    credentials_ref: str | None       # NAME of an env var holding secrets, never the secret itself
    options: dict = {}                # source-type-specific knobs, see below
```

Common `options` keys (all optional):

- `field_map`: maps the sources actual column names to canonical
  `Transaction` field names (see "Schema drift" below).
- `retries` / `retry_base_delay`: override the default retry count (3) and
  base backoff delay (0.5s).
- `timeout` (API only): request timeout in seconds, default 5.0.
- `host`, `port`, `local_dir` (SFTP only): connection details; `local_dir`
  is where the fetched file is staged before parsing.

**Known limitation:** as of A18, none of the real source tools
(`csv_read_tool`, `api_fetch_tool`, `sftp_fetch_tool`) actually raise the
`FetchError` that triggers a retry -- they all catch their own failures
internally and record an error issue on the first attempt instead. The
retry machinery (`with_retry`, `RateLimiter`) is fully built and fully
unit-tested, but does not currently engage on a real transient failure.
Tracked for the A19 bug bash, not fixed here -- see `datagents/resilience.py`
and `datagents/agents/ingestion_agent.py` docstrings for the mechanism as
designed.

## Secrets: credentials_ref

For SFTP, never put a real username/password in `options`. Set
`credentials_ref` to the NAME of an environment variable containing
"username:password"; the ingestion agent reads it from `os.environ` at
call time (`_resolve_sftp_credentials` in `ingestion_agent.py`). Falling
back to `options["username"]`/`options["password"]` only happens when
`credentials_ref` is unset -- meant for local dev/tests with an injected
fake `sftp_client`, which never actually authenticates with those values
anyway. An automated test (`test_no_hardcoded_credentials_in_source`)
scans the whole codebase for anything that looks like a literal hardcoded
credential.

## Schema drift

Real sources rename, reorder, or drop columns over time. `field_map_tool`
handles renames (pass `options={"field_map": {...}}` as shown earlier).
A source with a genuinely missing required field, or a required field
renamed with no `field_map` supplied, is not silently accepted -- the row
is rejected and recorded as an issue, it never crashes the run. See
`datagents/tests/test_source_drift_matrix.py` for the full matrix of
drift scenarios tested across all three source types.

## Currency and entity normalization

`normalize_transactions` (in `normalization_agent.py`) converts every
transaction to USD (fixed demo FX rates in `normalization_tools.FX_TO_USD`)
and resolves counterparty name variants to a canonical form via a 3-tier
lookup: a small hardcoded `ALIAS_TABLE`, then a persistent on-disk
`AliasStore` cache, then an LLM call (only if a `gateway` is supplied;
`None` by default in production, so zero LLM calls unless something
explicitly opts in).

`AliasStore` writes an append-only NDJSON log (`alias_cache.json` by
default) so a name resolved once is remembered across runs without
re-calling the LLM. As of A17, this is an O(1)-per-write append, not an
O(n) full-file rewrite -- the earlier version rewrote the whole cache
file on every single resolution, which took about 30 seconds at 10k rows
with all-new counterparties. See `datagents/tools/alias_store.py`s module
docstring and `datagents/tests/test_ingestion_performance.py` for the
benchmark that caught it.

## Validation

`validate_transactions` (`validation_agent.py`) runs four deterministic
checks against every transaction -- `completeness_tool` (blank txn_id or
counterparty), `dedupe_tool` (duplicate txn_id), `format_tool`
(non-positive amount), `fx_check_tool` (currency not in
`normalization_tools.FX_TO_USD`) -- then, only for rows that pass every
check but have no `reference` to anchor them, optionally asks an LLM
(guardrailed into a strict `LLMVerdict` shape) whether the row needs human
review. A row is escalated (severity "review", routed straight to the HITL
resolution queue, no retry) when the LLM says "review", its confidence is
below 0.7, or its answer doesnt parse into the expected shape at all.

Note: `datagents/tools/completeness_tool.py` and
`datagents/tools/dedupe_tool.py` are dead stub files -- the real
implementations of both live in `datagents/tools/validation_tools.py` and
are what `validation_agent.py` actually imports and uses. Nothing in the
codebase imports the stub files (confirmed by grep). Dont be misled by the
filenames into thinking theyre the live code.

## Performance (A17)

Verified benchmarks on 10k rows (see
`datagents/tests/test_ingestion_performance.py`):

| Stage | Scenario | Time | Target |
|---|---|---|---|
| CSV ingest | 10k clean rows | ~0.08s | < 2s |
| Normalize | 10k rows, worst case (every counterparty a fresh cache miss) | ~0.2s | < 5s |

Memory: peak usage stays flat (roughly 11-14 MB) across repeated runs of
the full 10k-row pipeline -- no leak.

## Running the tests

```
pytest datagents/ -q                  # data-agent unit/integration tests
pytest datagents/tests/test_ingestion_performance.py -q   # A17 perf test specifically
pytest -q                             # whole repo, all interns
```

## Tool catalog

See `docs/data_agents/TOOL_CATALOG.md` for every tool/agent, its module
path, inputs/outputs, and whether its registered in `recon_platform`s
`ToolRegistry`.

## Sequence diagram

See `docs/data_agents/sequence_diagram.md` for the call sequence through
ingestion -> validation -> normalization, both standalone and as wired
into the full graph (including the validation-failure retry loop back to
ingestion).
