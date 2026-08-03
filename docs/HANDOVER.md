# Retro + Handover (C20 / M4)

## Retro

**What went well**
- Cross-track integration (B11, C11-C15, A11 wiring) surfaced real bugs
  *because* they were tested end-to-end on real data, not mocked pieces in
  isolation. Every "found and fixed" entry in `docs/BUG_BASH.md` and the
  git history only exists because something was actually run, not just
  reviewed by eye.
- The env->test->commit->push discipline (never push without a green run)
  held throughout, even under time pressure. It caught real regressions
  before they landed (the B11 chromadb-coupling bug, the C16
  double-processing bug, the C19 dead-LLM-gateway bug).
- Cross-review between tracks worked: Intern A caught two real bugs in C's
  code (the `retry_count` infinite-loop risk, the "any single bad row
  blocks the whole run" gate bug) just by reading the diff carefully.

**What was hard**
- A large chunk of one session was consumed by an environment problem
  (the repo living inside iCloud Drive's synced Desktop folder made every
  test run take 5-17 minutes instead of under a second). Moving the repo
  fixed it entirely -- worth doing on day one next time, not hours in.
- Branch discipline needed active attention. B-track and C-track work
  landed on the same branch for a stretch before being deliberately
  re-separated; A11-A13 ended up on `intern-b`/`intern-c` rather than
  `intern-a` itself. Neither caused data loss, but both needed explicit
  fixes (fast-forward syncs) rather than being cleanly avoidable in
  hindsight -- worth agreeing on a branch convention explicitly up front
  next time, not inferring it as you go.
- `ReconState`'s "undeclared key gets silently dropped by a compiled
  `StateGraph`" behavior bit the project twice (once for A's
  `book_source_configs`/`bank_source_configs`, once for `ingestion_metrics`)
  before it was understood and documented. Worth calling out explicitly
  in onboarding for anyone joining this codebase.

## Handover

**For anyone picking this up next:**

1. Read `docs/ARCHITECTURE.md` first -- it's kept accurate to the actual
   code, including an honest "Known gaps" section. Then `docs/RUNBOOK.md`
   for how to actually run things (every command in it is verified, not
   aspirational).
2. Check `docs/BUG_BASH.md` before assuming anything works -- it's the
   record of what was actually found broken and fixed, with test names.
3. `intern-b` and `intern-c` have diverged in both directions at various
   points (see git log on each). Before starting new work, check which
   branch actually has what you need -- don't assume one is a strict
   superset of the other.
4. The three "Known gaps" in `ARCHITECTURE.md` are real, open items, not
   just disclaimers -- `learning_node`'s exception-pattern mining, A11-13's
   branch location, and `score_risk`'s untuned weights are all genuine
   next steps.

**Remaining plan items not yet started:** A15, B15 already exist on
`intern-b` (B15/B16 landed there); A14 also landed on `intern-b`. C-track
is complete through C20. A15 and any further hardening/perf work (A16-A17,
B16-B17 territory already partially covered by B16) are the natural next
steps, plus a final combined-branch merge and live three-segment demo once
A20/B20 exist.
