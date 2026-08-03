# Data Sub-graph Tool Catalog

Every function used by the ingestion -> validation -> normalization
pipeline. "Registered" means its discoverable via
`recon_platform.registry.registry.get("<name>")` / `.list_tools()`; agent
functions and orchestration functions are called directly by the
graph/sub-graph, not looked up dynamically, so theyre not registered.

## Agents (LangGraph nodes / orchestration)

| Function | Module | Input | Output |
|---|---|---|---|
| `ingestion_agent(state)` | `datagents/agents/ingestion_agent.py` | `state["source_configs"]` | transactions, issues, ingestion_metrics |
| `validation_agent(state, gateway=None)` | `datagents/agents/validation_agent.py` | `state["transactions"]` | validation_findings, issues |
| `normalization_agent(state, base=USD, gateway=None, store=None)` | `datagents/agents/normalization_agent.py` | `state["transactions"]` | normalized_transactions |
| `run_data_subgraph(state, ...)` | `datagents/data_subgraph.py` | combined state, one source list | merged state through all 3 stages |
| `run_data_subgraph_by_source(named_configs, ...)` | `datagents/data_subgraph.py` | dict of name to source list | merged state, per-name transactions kept separate |

## Source tools (registered)

| Tool | Registry name | Module | Notes |
|---|---|---|---|
| CSV reader | `csv_read_tool` | `datagents/tools/csv_read_tool.py` | Reads via utf-8-sig (tolerates Excel BOM). Bad rows become an issue, not a crash. |
| API fetcher | `api_fetch_tool` | `datagents/tools/api_fetch_tool.py` | Real httpx.get. Any failure becomes an issue, not a crash. Does NOT raise FetchError (see README known limitation). |
| SFTP fetcher | `sftp_fetch_tool` | `datagents/tools/sftp_fetch_tool.py` | Real paramiko SSH/SFTP, or an injected sftp_client for tests. Downloads then delegates to csv_read_tool. Does NOT raise FetchError. |
| Field remapper | `field_map_tool` | `datagents/tools/field_map_tool.py` | Pure dict-key rename, no-op if field_map is falsy. Used by all three source tools above. |

## Validation tools (registered, all in validation_tools.py)

| Tool | Registry name | Flags |
|---|---|---|
| Completeness check | `completeness_tool` | MISSING_FIELD -- blank txn_id or counterparty |
| Duplicate check | `dedupe_tool` | DUPLICATE_TXN -- repeated txn_id |
| Amount format check | `format_tool` | NON_POSITIVE_AMOUNT -- amount is 0 or negative |
| FX support check | `fx_check_tool` | UNSUPPORTED_CURRENCY -- currency not in normalization_tools.FX_TO_USD |

ReasonCode.AMBIGUOUS (no reference, sent to LLM) is produced separately by
validation_agent._judge_ambiguous, not one of the four tools above.

**Dead code, do not confuse with the above:** `datagents/tools/completeness_tool.py`
and `datagents/tools/dedupe_tool.py` are stub files (pass-only bodies) left
over from an earlier layout. Nothing imports them. The real, live
implementations are the ones in the table above, inside validation_tools.py.

## Normalization tools (registered, all in normalization_tools.py)

| Tool | Registry name | Behavior |
|---|---|---|
| FX conversion | `fx_rate_tool` | Exact Decimal conversion via a fixed rate table (FX_TO_USD), rounded to the cent. |
| Entity alias resolution | `entity_alias_tool` | 3-tier: hardcoded ALIAS_TABLE, then AliasStore cache, then LLM only if gateway is given. |
| Reference canonicalization | `canonicalize_reference_tool` | Trim and uppercase; None stays None. |

## Supporting infrastructure (not registered as tools, but load-bearing)

| Component | Module | Purpose |
|---|---|---|
| `AliasStore` | `datagents/tools/alias_store.py` | Persistent on-disk cache for entity_alias_tool. NDJSON append-only log as of A17 (was O(n^2) full-file rewrite before). Auto-migrates an old-format cache file on load. |
| `FetchError` / `with_retry` | `datagents/resilience.py` | Exponential-backoff retry helper. Fully built and unit-tested, but no production source tool currently raises FetchError -- see README known limitation. |
| `RateLimiter` | `datagents/resilience.py` | Enforces a minimum interval between consecutive calls to a source, applied before every attempt in ingestion_agent._run_source, including retries. Opt-in, no pacing by default. |
| `ToolSpan` / `timed()` | `datagents/observability.py` | Per-source metrics: rows in/out, retry attempts, duration, status. Surfaced on graph state as ingestion_metrics. |
| `ToolRegistry` | `recon_platform/registry.py` | Central name to callable lookup all the registered tools above use. |
| `LLMGateway` / `MockLLMGateway` | `recon_platform/gateway/llm_gateway.py` | Abstraction every agent calls instead of a provider SDK directly. MockLLMGateway returns a canned response, used throughout tests. |

## Schemas (datagents/schemas.py)

| Type | Purpose |
|---|---|
| `SourceType` | Enum: CSV, API, SFTP. |
| `Currency` | Enum of 8 supported ISO 4217 currencies. |
| `Transaction` | The core normalized record: txn_id, date, amount, currency, counterparty, reference, source. |
| `SourceConfig` | Describes one source to ingest: name, source_type, location, credentials_ref, options. |
| `IngestResult` | What a source tool / the ingestion agent returns: transactions, issues, rows_read, plus an .ok property. |

(ValidationFinding, ReasonCode, LLMVerdict live in
datagents/tools/validation_tools.py, not schemas.py.)
