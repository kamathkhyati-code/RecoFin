# Demo Segment B: Matching, Exception, Learning (Reasoning Track)

Live-run script for the reasoning half of the pipeline. Each numbered
step is a command to actually run in front of the audience -- nothing
here is a screenshot or a pre-recorded output. Talking points are in
*italics* under each step.

Setup, before the audience is watching:
```powershell
cd C:\Users\mann_\Projects\RecoFin
.venv\Scripts\Activate.ps1
```

## Segment 1: Deterministic matching (exact -> tolerance -> fuzzy)

**Step 1 -- show the matching agent runs strongest-first, no double-matches:**
```powershell
python -m pytest reasoning\tests\test_matching_agent.py -v
```
*"The matching agent runs three strategy tools strongest-first --
exact match, then amount/date tolerance, then fuzzy reference
similarity -- retiring matched transactions between passes so nothing
is ever matched twice. These six tests prove that on a fixture with a
clean pair for every strategy."*

**Step 2 -- run the eval dashboard live (this is the required deliverable: "eval dashboard shown"):**
```powershell
python -m reasoning.evals.generate_match_eval_report
```
*"This is our eval dashboard. It runs the matcher on a labeled golden
dataset through three layers -- deterministic only, plus an LLM
escalation path, plus retrieval-augmented match memory -- and reports
precision, recall, auto-match rate, and hallucination rate for each.
Watch recall: deterministic alone misses two pairs where the wording is
too different for string similarity to catch. Adding the LLM layer
recovers both with zero precision loss. Adding memory doesn''t change
which pairs match -- it raises confidence on the pair we''ve seen
before, which is what pushes it from ''needs a human look'' to
''safe to auto-apply.''"*

**Step 3 -- prove the auto-match threshold holds under adversarial input, and matching scales:**
```powershell
python -m pytest reasoning\tests\test_adversarial_matching.py reasoning\tests\test_matching_performance.py -v
```
*"The auto-match threshold (0.85) isn''t a guess -- it''s read directly
off the eval numbers you just saw. These five adversarial tests throw
tricky cases at it: two transactions in different currencies that
otherwise look identical, near-duplicate amounts on genuinely unrelated
payments, and confusingly similar invoice numbers -- and confirm the
system never lets a coincidental match through as unreviewed. The last
test proves the whole matching pipeline handles 10,000 transactions per
side in well under a second, so this scales past a toy demo dataset."*

## Segment 2: Exception + learning, end to end

**Step 4 -- run the whole matching -> exception -> learning chain on one command:**
```powershell
python -m pytest reasoning\tests\test_match_subgraph.py -v
```
*"`run_match_subgraph` is the single entry point that chains everything
together: deterministic matching, optional LLM escalation, hallucination
guard and memory calibration, then classifies whatever''s left over into
exceptions, and -- when a rule store is wired in -- applies any
approved learning-agent rule suggestions on the very next run. These
tests prove the whole chain composes correctly on real state, which is
exactly what integration (B11) plugged into the live graph."*

## Segment 3: Hardened and proven

**Step 5 -- close with the full repo suite, green:**
```powershell
python -m pytest -q
```
*"Everything you just watched -- matching, the eval dashboard,
adversarial edge cases, the full exception/learning chain -- sits
inside a suite of over two hundred tests, all green, including a bug
bash that found and fixed a real defect: duplicate transaction IDs used
to silently drop a legitimate match with no warning. That now fails
loudly instead, which is the difference between a demo that looks good
and a system you can actually trust with real reconciliation data."*

## Rehearsal checklist (run through this once, alone, before presenting)

- [ ] Fresh terminal, venv activated, on `intern-b`, `git pull` done.
- [ ] Step 1 passes (matching agent tests).
- [ ] Step 2 prints the ablation table with the expected recall jump.
- [ ] Step 3 passes (adversarial + performance).
- [ ] Step 4 passes (match subgraph, full chain).
- [ ] Step 5 passes (full suite green).
- [ ] Know the one number cold: **recall goes 0.75 -> 1.0** when the LLM
      layer is added, with **zero precision loss** -- that''s the single
      most demo-able sentence in this whole segment.
