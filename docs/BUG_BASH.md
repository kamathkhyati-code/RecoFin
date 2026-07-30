# C19: Bug Bash Triage Board

Ran against `intern-c` at commit `01bf03c` (post-C18), full read-through of
every module not already scrutinized in earlier sessions, plus targeted
empirical checks (not just code reading) on anything that touches shared
state or module-level singletons.

## Findings

| # | Severity | Area | Finding | Status |
|---|---|---|---|---|
| 1 | **Critical** | `recon_platform/graph/build.py` | `build_graph()` never wired an `LLMGateway` into `validation_node`, `normalization_node`, or `matching_node`. Every LLM-escalation feature in the system -- B5's semantic matching, A6/A7's ambiguous-row fallback, A9's entity alias resolution -- was individually built and tested standalone, but silently unreachable dead code when actually running through the real compiled graph. Confirmed empirically: a `MockLLMGateway` passed to the old `build_graph()` received zero calls even when normalization hit a name outside the hardcoded alias table. | **Fixed.** Added an optional `gateway` param to `build_graph()` and the three affected nodes (default `None`, fully backward compatible), bound via `functools.partial` at graph-construction time. Regression test: `tests/test_c19_bug_bash.py::test_gateway_is_reachable_through_real_graph` proves a real LLM call now happens through the compiled graph; a companion test proves the no-gateway default still makes zero calls. |
| 2 | **Medium** | `datagents/tools/alias_store.py` + `.gitignore` | `AliasStore`'s default path (`"alias_cache.json"`) is relative to whatever the current working directory happens to be, and `recon_platform/graph/build.py` holds it as a module-level singleton (`_ALIAS_STORE = AliasStore()`) -- intentional by A9's own design (a 2nd run should make zero LLM calls), but the resulting file was never gitignored, so a real cache file could be accidentally committed. Confirmed the hazard is real: a manual verification script written during this bash left a stray `alias_cache.json` in the repo root, which then silently changed a *later*, unrelated pytest run's outcome (a fixed-name test went from "2 LLM calls" to "0 LLM calls" purely because of leftover disk state). | **Fixed.** Added `alias_cache.json` to `.gitignore`. Rewrote the affected test to use a uuid-suffixed counterparty name so its outcome can never depend on ambient cache state. This is not a product bug (the persistence is correct, intentional behavior) -- it's a git-hygiene gap plus a lesson about testing against a persistent singleton. |
| 3 | Info | `datagents/agents/ingestion_agent.py` | Not a defect -- flagging because it's a good example to reference: Intern A already found and fixed a related class of bug independently (`FetchError` used to propagate out of `_run_source` and crash the whole run instead of degrading to a recorded, `row_ref=None` issue like every other failure mode). Documented in that file's own docstring; verified the fix is real and consistent with `validation_gate`'s row_ref-based critical/non-critical distinction (C-track fix from earlier in the week). | No action needed -- confirmed correct. |
| 4 | Info | `datagents/observability.py`, `datagents/tools/field_map_tool.py`, `datagents/tools/validation_tools.py` (`completeness_tool`/`dedupe_tool`/`format_tool`/`fx_check_tool`) | Full read-through, no defects found. All four validation tools correctly produce row-level findings (`row_ref` set via the `txn_id` they attach to), so none of them can wrongly trigger a batch-level run-block regardless of `severity`. | No action needed. |

## Verification

Full suite (`datagents/` + `reasoning/` + `tests/`), golden data, `intern-c`:

```
209 passed
```

(207 pre-bash baseline + 2 new regression tests for finding #1.)

No critical or medium-severity defects remain open.
