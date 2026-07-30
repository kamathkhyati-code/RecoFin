# Reasoning Track (`reasoning/`)

The reasoning package is the second half of the recon pipeline: once
`datagents/` has produced normalized book and source transactions, this
package matches them, classifies whatever is left over, learns from what
gets resolved, and grows a memory of confirmed matches over time.

Pipeline shape:
`reasoning/match_subgraph.py` wires the first five stages together as one
callable unit (`run_match_subgraph`), which is what the eval harness and
the adversarial tests exercise directly, without needing the full
LangGraph wired up.

## Matching agent (`agents/matching_agent.py`, `tools/matching_tools.py`)

`run_matching(book, source)` runs three strategy tools **strongest-first**,
retiring matched transactions between passes so nothing is ever matched
twice:

1. **`exact_tool`** -- identical currency, amount, date, and reference.
   Confidence always 1.0.
2. **`tolerance_tool`** -- amount within a tolerance (default 0.05) and
   date within a window (default 2 days). Confidence scales with how
   close the amount/date are to exact.
3. **`fuzzy_tool`** -- same currency and amount (within tolerance), but
   the reference is compared with `difflib` string similarity instead of
   exact match. Confidence scales with the similarity ratio.

All three tools are registered in the shared `ToolRegistry`
(`recon_platform/registry.py`) under their own names, so
`matching_agent` resolves them by name rather than importing them
directly -- this is what "strongest-first, tool-based" means in the
Architecture tab.

**Scaling (B17):** the tools used to be plain `O(n*m)` nested loops,
which does not survive 10k-transaction inputs. They now use bucketed and
binary-searched lookups instead:
- `exact_tool` buckets source transactions by
  `(currency, amount, date, normalized_reference)` -- an exact match is
  an `O(1)` dict lookup per book transaction.
- `tolerance_tool` and `fuzzy_tool` bucket source transactions by
  currency, sort each bucket by amount, and binary-search (`bisect`) the
  amount-tolerance window instead of scanning every source transaction.
- Normalized reference strings are computed once per transaction and
  reused, instead of being recomputed on every comparison.

This changed *how fast* candidates are found, not *which* candidates are
found or their confidence -- see `reasoning/tests/test_matching_tools_correctness.py`,
which cross-checks the production tools against an independent
brute-force reference implementation across five random seeds.

## Semantic matching / LLM escalation (`agents/semantic_match_agent.py`)

Only runs on whatever `matching_agent` left unmatched, and only ever
considers pairs with the same currency and amount within a tight
tolerance (0.01) -- it judges *wording*, not numbers. The LLM's raw
output is forced through `SemanticJudgment` (a strict pydantic schema)
via `validate_with_retry` (guardrails), so a malformed response is
retried rather than silently accepted. The resulting `MatchResult`'s
transaction IDs always come from the real candidate loop, never parsed
out of the LLM's text -- this is *why* the hallucination guard never
finds anything to reject on this path by construction.

## Confidence calibration + hallucination guard (`agents/calibrated_matcher.py`)

Two jobs, always in this order:
1. **Guard first.** `guard_against_fabricated_ids` rejects (raises
   `HallucinationError`) any `MatchResult` citing a book/source ID that
   was never in the candidate set. This runs on every match, from every
   layer, before anything else happens.
2. **Calibrate second** (only if a memory store is supplied). Blends raw
   confidence with how close the pair is to its nearest neighbour in
   match memory, capped at a +0.15 boost so memory alone can never
   manufacture certainty.

## Auto-match threshold (`thresholds.py`, tuned in B16)

`AUTO_MATCH_THRESHOLD = 0.85` is the line between "safe to auto-apply"
and "needs a human look." It isn't arbitrary -- it's read directly off
the B15 ablation numbers: exact matches sit at 1.0, well-formed
tolerance/fuzzy matches on the golden set score comfortably above 0.85,
and a coincidental near-duplicate match (amount/date proximity with no
real reference support) scores well below it. `split_auto_and_review`
is what a caller should use to separate the two buckets;
`reasoning/tests/test_adversarial_matching.py` proves the floor holds
under adversarial inputs (currency edges, near-duplicate amounts,
confusable references).

## Exception agent (`agents/exception_agent.py`, `agents/exception_escalation.py`)

Takes whatever `matching_agent` (and, if run, the semantic path) left
unmatched on both sides and classifies each leftover transaction,
risk-scores it, and drafts a resolution note. Unresolved exceptions are
routed to a human-in-the-loop review queue
(`exception_escalation.py`); a resolved exception updates state
idempotently rather than duplicating.

## Learning agent + rule store (`agents/learning_agent.py`, `rule_store.py`)

Mines recurring patterns out of resolved tolerance/fuzzy matches and
exceptions (for example: "widen tolerance" or "lower the fuzzy
threshold") and writes them as `RuleSuggestion`s to the rule store. Once
a suggestion is approved, `apply_approved_rules(rule_store)` turns it
into a `tool_config` override that `matching_agent`/`run_matching`
accepts directly -- so an approved suggestion changes live matching
behavior on the very next run, with no extra plumbing.

## Match memory / RAG (`memory/match_memory.py`, `memory/embeddings.py`)

`MatchMemory` wraps a Chroma collection of confirmed `(book, source)`
match pairs, embedded as `"{book.counterparty} {book.reference} |
{source.counterparty} {source.reference}"`. `retrieve_nearest` returns
the closest historical matches (lower distance = more similar) for a
candidate pair, which is what `calibrated_matcher` uses to boost
confidence. `run_match_subgraph` upserts each run's *confirmed* matches
back into memory after calibration, so the memory grows from its own
history run over run (B13) -- but never influences the same run's own
matches, only future ones, unless the caller pre-seeds it (see the eval
harness below).

## Reproducing the B15 matching eval + ablation report

This is the one thing anyone reading these docs should be able to do
without asking a teammate anything.

**1. Activate the environment and run the eval suite:**

```powershell
.venv\Scripts\Activate.ps1
python -m pytest reasoning\tests\test_match_eval.py -v
```

Expect 7 tests to pass, proving (a) the deterministic layer alone misses
the semantic-only golden pairs, (b) adding the LLM layer recovers them
with no precision loss, and (c) adding match memory boosts confidence
for the pair with prior history without changing recall.

**2. Generate the human-readable report:**

```powershell
python -m reasoning.evals.generate_match_eval_report
```

This prints the ablation table to the console and writes
`reasoning/evals/match_eval_report.md`. The golden dataset is fixed and
deterministic (`reasoning/evals/golden_matching_dataset.py`, no random
seed involved), and the LLM layer uses `ScriptedSemanticGateway` -- a
scripted stand-in, not a live API call -- so the report''s numbers are
exactly reproducible every time:

| Layer | Matched | Precision | Recall | Auto-match rate | Hallucination rate |
|---|---|---|---|---|---|
| det_only | 6 | 1.0 | 0.75 | 0.6667 | 0.0 |
| det_plus_llm | 8 | 1.0 | 1.0 | 0.5 | 0.0 |
| det_plus_llm_plus_rag | 8 | 1.0 | 1.0 | 0.625 | 0.0 |

**3. Run the adversarial suite (B16) and the 10k-scale perf test (B17):**

```powershell
python -m pytest reasoning\tests\test_adversarial_matching.py reasoning\tests\test_matching_performance.py -v
```

Expect 5 adversarial tests and 1 performance test to pass; the
performance test asserts all three matching tools combined finish
within a 5-second budget at 10,000 book x 10,000 source transactions
(measured well under 1 second on a normal dev machine).

**4. Run everything reasoning-related at once:**

```powershell
python -m pytest reasoning\ -q
```

**5. Run the whole repo (reasoning + data-agent + platform tests) to
confirm nothing else broke:**

```powershell
python -m pytest -q
```
