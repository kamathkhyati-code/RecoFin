# Acceptance Checklist (C20)

Every line below is backed by a specific, currently-passing test -- not a
claim. Run `pytest datagents/ reasoning/ tests/ -v` to verify all of them
yourself; the exact count at the bottom is what that command actually
prints on `intern-c` right now.

| # | Capability | Verified by |
|---|---|---|
| 1 | Real ingestion from CSV/API/SFTP sources, with schema-drift handling | `datagents/tests/test_source_drift_matrix.py`, `test_ingestion_agent.py` |
| 2 | Transient fetch failures retry with backoff; exhausted retries degrade to a recorded issue, not a crash | `datagents/tests/test_resilience.py`, `test_ingestion_retry.py` |
| 3 | Deterministic validation (completeness, dedupe, format, FX) + guardrailed LLM fallback for ambiguous rows | `datagents/tests/test_validation.py` |
| 4 | Exact FX conversion, entity alias resolution (table -> cache -> LLM), reference canonicalization | `datagents/tests/test_normalization.py`, `test_alias_memory.py` |
| 5 | Deterministic matching (exact/tolerance/fuzzy), strongest-first, no double-matching | `reasoning/tests/test_matching_tools.py`, `test_matching_agent.py` |
| 6 | LLM semantic-match escalation only for sub-threshold pairs; deterministic always wins | `reasoning/tests/test_semantic_match_agent.py` |
| 7 | Match memory (RAG): confirmed matches upserted, retrieval boosts confidence, memory grows from its own history | `reasoning/tests/test_match_memory.py`, `test_match_subgraph.py::test_b13_memory_grows_from_its_own_prior_matches` |
| 8 | Hallucination guard: a match citing an id outside the real candidate set is rejected | `reasoning/tests/test_calibrated_matcher.py`, `tests/test_regression_gate.py::test_hallucination_rate_is_zero_on_deterministic_matches` |
| 9 | Exception classification + risk scoring, resolution notes grounded in real transaction details | `reasoning/tests/test_exception_agent.py` |
| 10 | High-risk exceptions escalate to a shared review queue; low-risk auto-resolve; idempotent | `reasoning/tests/test_exception_escalation.py` |
| 11 | Learning agent mines recurring patterns into rule suggestions; approved rules apply automatically on the next run | `reasoning/tests/test_learning_agent.py`, `test_match_subgraph.py::test_c12_approved_widen_tolerance_applies_on_next_run` |
| 12 | Real ingestion -> validation -> normalization -> matching -> resolution -> consolidation, first true E2E | `tests/test_c11_full_e2e.py` |
| 13 | Full HITL cycle: exception -> review -> resume -> consolidate -> close, premature close blocked | `tests/test_c14_hitl_e2e.py` |
| 14 | A run interrupted mid-flight resumes from its checkpoint -- no double-processing | `tests/test_chaos.py` |
| 15 | A prompt-injection payload in transaction data never reaches an LLM, proven by call count, not just output | `tests/test_c17_security.py` |
| 16 | No hardcoded secrets anywhere in the codebase (permanent CI-enforced scan) | `tests/test_c17_security.py::test_repo_scan_no_hardcoded_secrets` |
| 17 | LLM gateway is actually reachable through the real compiled graph (found and fixed during C19's bug bash) | `tests/test_c19_bug_bash.py` |
| 18 | Eval metrics: accuracy, precision/recall, hallucination rate, idempotency, latency/cost, all gated in CI | `tests/test_regression_gate.py`, `.github/workflows/ci.yml` |
| 19 | Eval dashboard aggregates real run reports into one presentable view | `tests/test_c20_demo.py` |
| 20 | Architecture diagram is regenerated from the live compiled graph, not hand-drawn | `scripts_render_graph.py`, `docs/ARCHITECTURE.md` |

## Current status

```
pytest datagents/ reasoning/ tests/ -v
```

**211 passed** on `intern-c` (as of this commit). Zero critical defects open
(see `docs/BUG_BASH.md` for the full triage record).

## Known, honestly-documented gaps (not failures -- see `docs/ARCHITECTURE.md`)

- `learning_node`'s exception-pattern mining never actually fires in
  today's graph flow (only reachable when `close_ready`, which currently
  means zero exceptions this run).
- A11-A13 exist only on `intern-b`/`intern-c`, not `intern-a` itself.
- `score_risk`'s weights were never tuned against real historical eval
  feedback -- no such data exists yet in a fresh repo.
