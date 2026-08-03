# A19: Bug Bash Triage Board (Data Side)

Ran a full E2E dry run of the compiled graph against golden/realistic data
on intern-a, then diffed against Khyati's intern-c (post C17/C19) since
her branch had already been independently bug-bashed and found two defects
in shared machinery this track also depends on. Both had already been
fixed on the reasoning side but never ported to the data-agent side, which
has the identical exposure. Full reconciliation documented in
recon_platform/graph/build.py's module docstring.

## Findings

| # | Severity | Area | Finding | Status |
|---|---|---|---|---|
| 1 | Critical | recon_platform/graph/build.py | build_graph() never wired an LLMGateway into validation_node, normalization_node, or matching_node -- every LLM-dependent feature (A6/A7 ambiguous-row fallback, A9 entity alias resolution, B5 semantic matching) was individually built and tested standalone, but silently dead code through the real compiled graph. This was independently found and fixed on intern-c (C19) -- but that branch predated A14's validation-escalation logic, so neither branch had both fixes together. Confirmed empirically with a MockLLMGateway that received zero calls through build_graph().invoke() despite an unresolvable counterparty name. | Fixed. Reconciled C19's functools.partial gateway-wiring approach with A14's severity/escalation logic. build_hitl_graph/build_graph now accept an explicit gateway param; the earlier module-level _LLM_GATEWAY singleton and its monkeypatch-based tests are retired in favor of passing the gateway explicitly. Regression tests: tests/test_a19_bug_bash.py::test_gateway_is_reachable_through_real_graph (+ a no-gateway control case). |
| 2 | Critical (security) | datagents/agents/validation_agent.py, datagents/tools/normalization_tools.py | Both send untrusted, externally-controlled transaction text (counterparty/reference from a CSV/API/SFTP feed) straight to an LLM gateway with zero defense against prompt injection. Khyati's C17 work had already found and fixed this exact class of risk on the reasoning side (semantic_match_agent.py) and built the guard module (recon_platform/guardrails/injection_guard.py), but it was never ported to the data-agent side, which has the identical exposure. | Fixed. Ported injection_guard.py and wired any_field_looks_like_injection/looks_like_injection into both files: an ambiguous row with an injection-looking counterparty/reference now escalates for human review without an LLM call; entity_alias_tool falls through to the unresolved (not fabricated) name instead of calling the gateway. Regression tests: tests/test_a19_bug_bash.py (2 tests) + tests/test_injection_guard.py (8 unit tests on the guard module itself). |
| 3 | Medium | .gitignore | alias_cache.json (AliasStore's on-disk cache, persistent by design per A9) and .env/*.db were never gitignored -- a real hazard, since a stray cache file could get committed or silently change a later, unrelated test run's outcome via leftover disk state. Also found and fixed independently on intern-c (C17/C19). | Fixed. Both patterns added to .gitignore. |
| 4 | Info | datagents/tools/alias_store.py, datagents/resilience.py | Both are the old (pre-A17) versions on intern-c -- the O(n^2) full-file-rewrite bug in AliasStore.set() and the not-yet-existing RateLimiter are already fixed on intern-a (A17/A16) but not yet on intern-c. Not a defect in this track's code; flagged so whoever eventually merges intern-c forward doesn't reintroduce the O(n^2) bug by taking her older version of this file. | No action needed on intern-a; flag for the eventual full merge. |
| 5 | Info | reasoning/agents/semantic_match_agent.py, recon_platform/graph/checkpointer.py | intern-c has additional fixes here (C17's injection-guard wiring already present; C16's resume-from-checkpoint fix) that are reasoning-side/platform-level, not data-side. Out of scope for A19 specifically -- flagged for B19/the eventual full merge, not fixed here. | No action needed for A19. |

## Verification

Full suite (datagents/ + reasoning/ + tests/), intern-a:

```
224 passed
```

(211 pre-bash baseline + 13 new: 2 gateway-wiring regression tests, 3
data-agent injection-guard regression tests, 8 injection-guard unit tests.)

No critical data-side defects remain open.
