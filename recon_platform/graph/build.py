"""LangGraph skeleton for the Agentic Recon pipeline.

Every node here is a placeholder: it just logs a message and passes state
through unchanged. Real agent logic gets swapped in by A, B, and C as their
work lands. This file defines the shape of the graph and the gate logic.

C4 adds: optional checkpointer for persistent, resumable state, and
optional interrupt_before for pausing execution mid-run.
"""

from __future__ import annotations

from langgraph.graph import StateGraph, START, END

from recon_platform.state import ReconState, AgentMessage, MessageRole


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
    return {"messages": [_log(MessageRole.MATCHING, "Matching complete.")]}


def resolution_node(state: ReconState) -> dict:
    return {"messages": [_log(MessageRole.RESOLUTION, "Exceptions resolved.")]}


def consolidation_node(state: ReconState) -> dict:
    return {"messages": [_log(MessageRole.CONSOLIDATION, "Consolidation complete.")]}


def learning_node(state: ReconState) -> dict:
    return {"messages": [_log(MessageRole.LEARNING, "Patterns learned.")]}


def has_errors_gate(state: ReconState) -> str:
    issues = state.get("issues") or []
    has_critical = any(i.severity == "error" for i in issues)
    return "resolution" if has_critical else "normalization"


def matched_gate(state: ReconState) -> str:
    return "resolution" if state.get("unmatched_count", 0) > 0 else "consolidation"


def close_ready_gate(state: ReconState) -> str:
    return "learning" if state.get("close_ready") else "end"


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
        has_errors_gate,
        {"resolution": "resolution", "normalization": "normalization"},
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
