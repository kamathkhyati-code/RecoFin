"""LangGraph skeleton for the Agentic Recon pipeline.

supervisor/ingestion/validation/normalization/consolidation/learning are
still placeholders: they just log a message and pass state through
unchanged, pending real A-side wiring at A11. matching and resolution are
real as of B11: they run B10's matching sub-graph and B9's exception
escalation respectively. This file defines the shape of the graph and the
gate logic.

C4 adds: optional checkpointer for persistent, resumable state, and
optional interrupt_before for pausing execution mid-run.
"""

from __future__ import annotations

from langgraph.graph import StateGraph, START, END

from reasoning.agents.exception_escalation import escalate_exceptions
from reasoning.match_subgraph import run_match_subgraph
from recon_platform.state import ReconState, AgentMessage, MessageRole
from recon_platform.graph.routing import validation_gate, matched_gate, close_ready_gate


def _log(role: MessageRole, text: str) -> AgentMessage:
    return AgentMessage(role=role, content=text)


def supervisor_node(state: ReconState) -> dict:
    return {"messages": [_log(MessageRole.SUPERVISOR, "Run planned.")]}


def ingestion_node(state: ReconState) -> dict:
    return {"messages": [_log(MessageRole.INGESTION, "Data ingested.")]}


def validation_node(state: ReconState) -> dict:
    return {"messages": [_log(MessageRole.VALIDATION, "Validation complete.")]}


def normalization_node(state: ReconState) -> dict:
    return {"messages": [_log(MessageRole.NORMALIZATION, "Normalization complete.")]}


def matching_node(state: ReconState) -> dict:
    """B11: real matching + exception classification (B10's sub-graph).

    Threads book_transactions/source_transactions through deterministic
    matching, hallucination-guarded calibration, and exception
    classification. If neither is present, this is a synthetic test state
    (e.g. HITL/e2e tests that inject matched_count/unmatched_count
    directly to isolate the pause/resume mechanism from real matching) --
    stay a pure pass-through exactly like the original placeholder,
    rather than overwriting those manually-set counts with zero.
    """
    book = state.get("book_transactions") or []
    source = state.get("source_transactions") or []
    if not book and not source:
        return {"messages": [_log(MessageRole.MATCHING, "Matching complete.")]}

    result = run_match_subgraph(dict(state))
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
    return {"messages": [_log(MessageRole.CONSOLIDATION, "Consolidation complete.")]}


def learning_node(state: ReconState) -> dict:
    return {"messages": [_log(MessageRole.LEARNING, "Patterns learned.")]}



def build_graph(checkpointer=None, interrupt_before: list[str] | None = None):
    """Assemble and compile the skeleton graph.

    checkpointer: pass a LangGraph checkpointer (e.g. SqliteSaver) to enable
        persistent, resumable state across process restarts. Omit for a
        stateless, non-resumable compile (used by earlier C3 tests).
    interrupt_before: node names to pause execution before. Used to test
        interrupt/resume behavior.
    """
    graph = StateGraph(ReconState)

    graph.add_node("supervisor", supervisor_node)
    graph.add_node("ingestion", ingestion_node)
    graph.add_node("validation", validation_node)
    graph.add_node("normalization", normalization_node)
    graph.add_node("matching", matching_node)
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
