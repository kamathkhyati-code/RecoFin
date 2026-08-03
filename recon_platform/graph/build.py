"""LangGraph skeleton for the Agentic Recon pipeline.

A11: ingestion/validation/normalization are now real (previously
placeholders). matching and resolution are real as of B11. This file
defines the shape of the graph and the gate logic.

A11 data-flow note: `Transaction` has no field recording which named
source_config it came from, so the only reliable way to keep book vs.
bank transactions separate through the pipeline is to ingest and
normalize them via two separate calls, not one merged call that gets
split apart afterward. Callers supply `book_source_configs` and
`bank_source_configs` (each a list[SourceConfig]) instead of a single
flat `source_configs` list. Validation still runs on the combined set,
since cross-source checks (e.g. dedupe) need to see both sides at once.

A13: ingestion_node now also records per-source ToolSpan metrics (rows
in/out, retry attempts, duration, status) via ingest_sources_with_metrics
and surfaces them as ingestion_metrics (declared in ReconState).

A14: validation_node escalates ambiguous rows (ValidationFinding.escalate,
via the gateway param) to human review through the same "resolution" HITL
interrupt point B9's matching exceptions already use -- see
validation_node's docstring for why the gateway is threaded as a
parameter rather than read off state.

A19 (bug bash, reconciling C19): build_graph() previously never actually
wired an LLMGateway into validation_node/normalization_node/matching_node
at all -- confirmed empirically (a MockLLMGateway received zero calls
through a real graph.invoke(), despite an unresolvable counterparty name)
while dry-running the full pipeline for this bug bash. Every LLM-dependent
feature (A6/A7's ambiguous-row fallback, A9's entity alias resolution,
B5's semantic matching) was individually built and tested standalone, but
silently dead code in production. Fixed by threading an explicit
gateway param through build_graph() into the three nodes via
functools.partial, replacing the earlier module-level _LLM_GATEWAY
singleton this file used to rely on: binding via functools.partial at
graph-construction time is still checkpointer-safe (the gateway is bound
to the node callable, never placed in graph state, so SQLite/msgpack
never has to serialize it -- the same constraint that ruled out state in
the first place), and it's more testable than monkeypatching a module
attribute. Tests now call build_graph(gateway=MockLLMGateway(...))
directly. This reconciles a real divergence found during A19: Khyatis
C19 fix was built on a build.py that predated A14's escalation logic, so
neither branch had both fixes together until now.

A19 also found and fixed: validation_node's ambiguous-row LLM fallback
and normalization_node's entity_alias_tool both sent untrusted, externally
supplied text (a transaction's counterparty/reference field, from a
CSV/API/SFTP feed someone else controls) straight to an LLM gateway with
no defense against prompt injection -- a gap Khyatis C17 work had already
found and fixed on the reasoning side (semantic_match_agent.py) and the
guard module itself (recon_platform/guardrails/injection_guard.py) already
existed on intern-c, but was never ported to the data-agent side. Fixed by
wiring the same guard into datagents/agents/validation_agent.py and
datagents/tools/normalization_tools.py -- see those files own docstrings.

C4 adds: optional checkpointer for persistent, resumable state, and
optional interrupt_before for pausing execution mid-run.
"""
from __future__ import annotations

import functools

from langgraph.graph import StateGraph, START, END

from datagents.agents.ingestion_agent import ingest_sources_with_metrics
from datagents.agents.normalization_agent import normalize_transactions
from datagents.agents.validation_agent import validate_transactions
from datagents.tools.alias_store import AliasStore
from datagents.tools.validation_tools import ReasonCode
from reasoning.agents.exception_escalation import escalate_exceptions
from reasoning.agents.learning_agent import learning_agent
from reasoning.match_subgraph import run_match_subgraph
from reasoning.memory.match_memory import MatchMemory
from reasoning.schemas import ReconReport
from recon_platform.gateway.llm_gateway import LLMGateway
from recon_platform.hitl.review_queue import pending_for_run
from recon_platform.state import ReconState, AgentMessage, MessageRole, IssueRecord
from recon_platform.graph.routing import validation_gate, matched_gate, close_ready_gate


def _log(role: MessageRole, text: str) -> AgentMessage:
    return AgentMessage(role=role, content=text)


def supervisor_node(state: ReconState) -> dict:
    return {"messages": [_log(MessageRole.SUPERVISOR, "Run planned.")]}


def ingestion_node(state: ReconState) -> dict:
    """A11: real ingestion, book and bank kept separate.

    Increments retry_count regardless: validation_gate reads retry_count
    to decide when a genuinely critical (batch-level) validation issue
    has exhausted its retries and should escalate to resolution instead
    of looping ingestion<->validation forever. Nothing else in the graph
    ever increments it, so this has to happen here.

    If no book_source_configs/bank_source_configs are supplied, this is a
    synthetic test state -- e.g. regression/HITL tests that inject
    book_transactions/source_transactions or issues directly into
    initial_state to isolate gate/retry logic from real ingestion (the
    same pattern matching_node's own docstring already relies on). Stay a
    pure pass-through except for the retry_count bump in that case,
    exactly like the original placeholder -- otherwise this node would
    silently wipe out whatever the test seeded.
    """
    book_configs = state.get("book_source_configs")
    bank_configs = state.get("bank_source_configs")

    if not book_configs and not bank_configs:
        return {
            "retry_count": state.get("retry_count", 0) + 1,
            "messages": [_log(MessageRole.INGESTION, "Data ingested.")],
        }

    book_result, book_spans = ingest_sources_with_metrics(book_configs or [])
    bank_result, bank_spans = ingest_sources_with_metrics(bank_configs or [])

    transactions = list(book_result.transactions) + list(bank_result.transactions)
    new_issues = list(book_result.issues) + list(bank_result.issues)
    combined_issues = list(state.get("issues", [])) + new_issues
    combined_metrics = list(state.get("ingestion_metrics", [])) + [
        s.as_dict() for s in book_spans + bank_spans
    ]

    content = (
        f"Ingested {len(book_result.transactions)} book txn(s), "
        f"{len(bank_result.transactions)} bank txn(s); {len(new_issues)} issue(s)."
    )
    return {
        "book_transactions": book_result.transactions,
        "source_transactions": bank_result.transactions,
        "transactions": transactions,
        "issues": combined_issues,
        "ingestion_metrics": combined_metrics,
        "retry_count": state.get("retry_count", 0) + 1,
        "messages": [_log(MessageRole.INGESTION, content)],
    }


def validation_node(state: ReconState, gateway: LLMGateway | None = None) -> dict:
    """A11: real validation over the combined book+bank transaction set.

    A14: an ambiguous row the LLM flagged for human review
    (ValidationFinding.escalate=True) is tagged severity="review" rather
    than "warning"/"error" -- distinct from _has_critical_issue's
    batch-level retry logic (routing.py), since this isn't a retryable
    failure, it's an individual row that genuinely needs a human decision.
    validation_gate routes "review" issues to the same "resolution"
    interrupt point B9's matching exceptions already use, so
    start_run_with_hitl/resume_with_decision (recon_platform/hitl/resume.py)
    work unchanged -- that machinery only checks whether the graph paused
    before "resolution", not why.

    Takes gateway as a parameter (bound via functools.partial in
    build_graph) rather than reading it off state: a live gateway object
    isn't checkpointer-serializable (msgpack can't encode it), and HITL
    runs persist state to SQLite between pause and resume -- confirmed
    this the hard way when a first attempt at threading the gateway
    through state broke the checkpointer. Tests that need to exercise the
    escalation path pass gateway=MockLLMGateway(...) directly, either to
    validation_node itself or to build_graph/build_hitl_graph.

    issues has no reducer on ReconState, so returning it from this node
    would silently replace whatever ingestion_node already put there.
    Concatenate instead so ingestion-level and validation-level issues
    both survive into the gate's check.

    C19: gateway defaults to None so this stays directly callable exactly
    as before (existing tests that call validation_node(state) are
    unaffected) -- build_graph(gateway=...) binds it via functools.partial
    when wiring the real graph. Before this fix, the real graph never
    passed a gateway at all, so A6/A7's ambiguous-row LLM fallback was
    silently unreachable in production even though it was built and
    tested standalone.
    """
    txns = state.get("transactions", [])
    findings = validate_transactions(txns, gateway=gateway)

    def _severity(f) -> str:
        if f.escalate:
            return "review"
        if f.reason == ReasonCode.AMBIGUOUS:
            return "warning"
        return "error"

    new_issues = [
        IssueRecord(
            source="validation",
            severity=_severity(f),
            message=f"{f.reason.value}: {f.detail}",
            row_ref=f.txn_id,
        )
        for f in findings
    ]
    combined_issues = list(state.get("issues", [])) + new_issues

    content = f"Validation complete: {len(findings)} finding(s), {len(new_issues)} issue(s) this step."
    return {
        "validation_findings": findings,
        "issues": combined_issues,
        "messages": [_log(MessageRole.VALIDATION, content)],
    }


_ALIAS_STORE = AliasStore()

# Integration audit (post-C20): module-level singleton so B13's match
# memory actually persists across matching_node calls within a process
# lifetime. Unlike _ALIAS_STORE, this stays in-memory only (chromadb's
# default ephemeral Client, no PersistentClient path exists for match
# memory yet) -- known gap, not silently-broken: growth resets on
# process restart, but within one run of the server it works as tested.
_MATCH_MEMORY = MatchMemory()


def normalization_node(state: ReconState, gateway: LLMGateway | None = None) -> dict:
    """A11: real normalization, book and bank normalized separately so
    matching_node's book_transactions/source_transactions stay populated.

    Uses a module-level AliasStore so the alias cache (A9) actually
    persists across nodes within a run and across process runs, instead
    of rebuilding an empty cache every time this node fires.

    C19: gateway defaults to None (see validation_node's docstring for
    why) -- without it, entity_alias_tool's LLM resolution for a
    counterparty name outside the hardcoded ALIAS_TABLE was silently
    unreachable through the real graph, always falling back to the
    unresolved name.
    """
    book_txns = state.get("book_transactions") or []
    source_txns = state.get("source_transactions") or []

    book_norm = normalize_transactions(book_txns, gateway=gateway, store=_ALIAS_STORE)
    source_norm = normalize_transactions(source_txns, gateway=gateway, store=_ALIAS_STORE)
    normalized = book_norm + source_norm

    content = (
        f"Normalized {len(book_norm)} book txn(s), {len(source_norm)} bank txn(s)."
    )
    return {
        "book_transactions": book_norm,
        "source_transactions": source_norm,
        "normalized_transactions": normalized,
        "transactions": normalized,
        "messages": [_log(MessageRole.NORMALIZATION, content)],
    }


def matching_node(state: ReconState, gateway: LLMGateway | None = None) -> dict:
    """B11: real matching + exception classification (B10's sub-graph).
    Threads book_transactions/source_transactions through deterministic
    matching, hallucination-guarded calibration, and exception
    classification. If neither is present, this is a synthetic test state
    (e.g. HITL/e2e tests that inject matched_count/unmatched_count
    directly to isolate the pause/resume mechanism from real matching) --
    stay a pure pass-through exactly like the original placeholder,
    rather than overwriting those manually-set counts with zero.

    C19: gateway defaults to None (see validation_node's docstring for
    why) -- without it, B5's LLM escalation for sub-threshold pairs was
    silently unreachable through the real graph; matching_node only ever
    ran the deterministic tools.

    Integration audit (post-C20): run_match_subgraph also accepts a
    `memory` param (B13's match memory/RAG -- confirmed matches upserted,
    retrieval boosts confidence, memory grows from its own history), but
    nothing here ever passed one, so that whole capability was built and
    tested (reasoning/tests/test_match_memory.py, test_match_subgraph.py)
    yet silently unreachable through the real graph, same class of bug as
    the gateway one above. Fixed by threading the module-level
    _MATCH_MEMORY singleton below, same pattern as _ALIAS_STORE -- it's a
    local embedding/retrieval step (HashingEmbeddingFunction), not an LLM
    call, so unlike gateway it's safe to wire in unconditionally rather
    than gating it behind an opt-in param.
    """
    book = state.get("book_transactions") or []
    source = state.get("source_transactions") or []
    if not book and not source:
        return {"messages": [_log(MessageRole.MATCHING, "Matching complete.")]}
    result = run_match_subgraph(dict(state), gateway=gateway, memory=_MATCH_MEMORY)
    matches = result["match_results"]
    exceptions = result["exceptions"]
    unmatched_total = len(result["unmatched_book"]) + len(result["unmatched_source"])
    content = (
        f"Matched {len(matches)} pair(s); {unmatched_total} unmatched, "
        f"{len(exceptions)} exception(s) classified."
    )
    return {
        "match_results": matches,
        "unmatched_book": result["unmatched_book"],
        "unmatched_source": result["unmatched_source"],
        "exceptions": exceptions,
        "matched_count": len(matches),
        "unmatched_count": unmatched_total,
        "messages": [_log(MessageRole.MATCHING, content)],
    }


def resolution_node(state: ReconState) -> dict:
    """B11: real exception escalation (B9) at the HITL gate.
    Runs whatever exceptions matching_node classified through B9's
    escalation logic: high-risk ones go to the shared review queue,
    low-risk ones are auto-resolved. Exceptions is empty for states that
    never carried real transactions, matching the placeholder's no-op
    behavior in that case.
    """
    exceptions = state.get("exceptions", []) or []
    run_id = state.get("run_id", "unknown-run")
    summary = escalate_exceptions(exceptions, run_id=run_id)
    content = (
        f"Escalated {len(summary['escalated'])}, "
        f"auto-resolved {len(summary['auto_resolved'])} exception(s)."
    )
    return {"messages": [_log(MessageRole.RESOLUTION, content)]}


def consolidation_node(state: ReconState) -> dict:
    """C11 (partial) + C14: build the run-level ReconReport from real state.
    matched_count/unmatched_count/exceptions are real as of B11 whenever
    matching_node actually ran on real transactions. close_ready is
    computed here rather than trusted from the caller: a run isn't
    genuinely close-ready while exceptions remain unresolved, regardless
    of what a caller set on initial_state.
    C14: close_ready checks the live review_queue for this run_id, not
    just whether any exceptions were classified -- an auto-resolved
    exception (B9) never blocks close; an escalated one does until an
    analyst resolves it (resolve_exception / review_queue.mark_resolved),
    even across a resumed HITL run. This is what makes close_period()'s
    guard (recon_platform/hitl/close_gate.py) meaningful rather than a
    flag nobody enforces.
    """
    matched = state.get("matched_count", 0)
    unmatched = state.get("unmatched_count", 0)
    exceptions = state.get("exceptions", []) or []
    total = matched + unmatched
    match_rate = matched / total if total else 0.0
    run_id = state.get("run_id", "unknown-run")
    close_ready = len(pending_for_run(run_id)) == 0
    report = ReconReport(
        run_id=run_id,
        period=state.get("period", ""),
        matched_count=matched,
        unmatched_count=unmatched,
        exception_count=len(exceptions),
        match_rate=match_rate,
        close_ready=close_ready,
    )
    content = (
        f"Consolidated: {report.matched_count} matched, "
        f"{report.exception_count} exception(s), close_ready={close_ready}."
    )
    return {
        "report": report,
        "close_ready": close_ready,
        "messages": [_log(MessageRole.CONSOLIDATION, content)],
    }


def learning_node(state: ReconState) -> dict:
    """C12: mine this run's matches into rule suggestions for approval.
    Persisted to the global rule_store by default (learning_agent's
    default). Once an analyst approves a suggestion (RuleStore.approve),
    the very next matching_node run picks it up automatically via
    apply_approved_rules -- no extra plumbing needed, closing the loop.
    Only reachable when close_ready (no exceptions this run, per
    consolidation_node), so exception-pattern mining never actually
    fires in today's graph flow -- that needs close_ready to mean
    "exceptions resolved" rather than "no exceptions occurred", which is
    C14's job. Tolerance/fuzzy pattern mining from match_results still
    works regardless.
    """
    matches = state.get("match_results") or []
    exceptions = state.get("exceptions") or []
    suggestions = learning_agent(matches, exceptions)
    content = f"Learning: {len(suggestions)} rule suggestion(s) mined this run."
    return {"rule_suggestions": suggestions, "messages": [_log(MessageRole.LEARNING, content)]}


def build_graph(
    checkpointer=None,
    interrupt_before: list[str] | None = None,
    gateway: LLMGateway | None = None,
):
    """Assemble and compile the skeleton graph.
    checkpointer: pass a LangGraph checkpointer (e.g. SqliteSaver) to enable
        persistent, resumable state across process restarts. Omit for a
        stateless, non-resumable compile (used by earlier C3 tests).
    interrupt_before: node names to pause execution before. Used to test
        interrupt/resume behavior.
    gateway: A19 fix (reconciling C19) -- an LLMGateway to bind into
        validation_node/normalization_node/matching_node, so B5's semantic
        matching, A6/A7's ambiguous-row fallback, and A9's entity alias
        resolution are actually reachable through the real graph. Omit to
        keep the run fully deterministic (no LLM calls at all, the prior
        default behavior -- every existing caller is unaffected).
    """
    graph = StateGraph(ReconState)
    graph.add_node("supervisor", supervisor_node)
    graph.add_node("ingestion", ingestion_node)
    graph.add_node("validation", functools.partial(validation_node, gateway=gateway))
    graph.add_node("normalization", functools.partial(normalization_node, gateway=gateway))
    graph.add_node("matching", functools.partial(matching_node, gateway=gateway))
    graph.add_node("resolution", resolution_node)
    graph.add_node("consolidation", consolidation_node)
    graph.add_node("learning", learning_node)
    graph.add_edge(START, "supervisor")
    graph.add_edge("supervisor", "ingestion")
    graph.add_edge("ingestion", "validation")
    graph.add_conditional_edges(
        "validation",
        validation_gate,
        {"resolution": "resolution", "normalization": "normalization", "ingestion": "ingestion"},
    )
    graph.add_edge("normalization", "matching")
    graph.add_conditional_edges(
        "matching",
        matched_gate,
        {"resolution": "resolution", "consolidation": "consolidation"},
    )
    graph.add_edge("resolution", "consolidation")
    graph.add_conditional_edges(
        "consolidation",
        close_ready_gate,
        {"learning": "learning", "end": END},
    )
    graph.add_edge("learning", END)
    return graph.compile(checkpointer=checkpointer, interrupt_before=interrupt_before)
