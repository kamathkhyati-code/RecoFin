"""Matching Agent (stub).

Real implementation will run matching strategy tools strongest-first
(exact, tolerance, fuzzy) and escalate hard cases to an LLM with RAG
over the match memory vector store. This is a placeholder so the graph
skeleton and other packages can import and wire against it early.
"""

from __future__ import annotations

from recon_platform.state import ReconState, AgentMessage, MessageRole


def matching_agent(state: ReconState) -> dict:
    """Placeholder matching agent node.

    Currently a no-op that logs a message and passes state through.
    Real logic lands later: exact_tool, tolerance_tool, fuzzy_tool,
    match_memory_retrieve.
    """
    return {
        "messages": [
            AgentMessage(role=MessageRole.MATCHING, content="Matching agent stub ran.")
        ]
    }
