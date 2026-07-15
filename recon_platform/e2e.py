"""Infra end-to-end smoke test with stub agents (M2 prep).

Wires together the checkpointer, HITL interrupt/resume, a guardrail-wrapped
stub agent, and the eval harness into a single traversal, to prove the
platform skeleton holds together before real agents (A/B) land.
"""

from __future__ import annotations

import json

from pydantic import BaseModel

from recon_platform.eval.dataset import GoldenRecord
from recon_platform.eval.harness import run_eval
from recon_platform.gateway.llm_gateway import MockLLMGateway
from recon_platform.graph.checkpointer import get_checkpointer
from recon_platform.guardrails.validators import validate_with_retry
from recon_platform.hitl.resume import build_hitl_graph, start_run_with_hitl, resume_with_decision
from recon_platform.hitl.review_queue import review_queue


class MatchPrediction(BaseModel):
    label: str


def _predict(input_dict: dict) -> str:
    return "matched" if input_dict.get("amount_a") == input_dict.get("amount_b") else "unmatched"


def _guardrail_wrapped_stub_agent(input_dict: dict) -> str:
    """Stub "agent": predicts a label, validated through the guardrail
    retry mechanism against a mock LLM gateway. This exercises C5's
    validation pipeline even though no real model call happens.
    """
    gateway = MockLLMGateway(canned_response=json.dumps({"label": _predict(input_dict)}))
    result = validate_with_retry(MatchPrediction, lambda: gateway.generate("classify"))
    return result.label


def run_e2e_smoke_test(db_path: str, output_dir: str) -> dict:
    """Run the full stubbed pipeline end to end and return a summary dict.

    Exercises: checkpointer persistence, HITL interrupt + resume, guardrail
    validation, and the eval harness, all in one traversal.
    """
    summary: dict = {}

    with get_checkpointer(db_path) as cp:
        graph = build_hitl_graph(cp)
        run_id = "e2e-smoke-1"
        initial_state = {
            "run_id": run_id,
            "period": "2026-06",
            "messages": [],
            "issues": [],
            "matched_count": 0,
            "unmatched_count": 2,
            "close_ready": True,
        }

        start_run_with_hitl(graph, run_id, initial_state)

        config = {"configurable": {"thread_id": run_id}}
        snapshot_before_resume = graph.get_state(config)
        summary["paused_before_resolution"] = "resolution" in snapshot_before_resume.next
        summary["review_item_registered"] = review_queue.get(run_id) is not None

        result = resume_with_decision(graph, run_id, decision={"unmatched_count": 0})
        role_values = [m.role.value for m in result["messages"]]
        summary["run_completed"] = "consolidation" in role_values
        summary["review_item_resolved"] = review_queue.get(run_id).resolved

        history = list(graph.get_state_history(config))
        summary["checkpoint_history_length"] = len(history)
        summary["resumable"] = len(history) > 1

    golden_records = [
        GoldenRecord(record_id="g1", input={"amount_a": 10, "amount_b": 10}, expected_label="matched"),
        GoldenRecord(record_id="g2", input={"amount_a": 10, "amount_b": 20}, expected_label="unmatched"),
        GoldenRecord(record_id="g3", input={"amount_a": 7, "amount_b": 7}, expected_label="matched"),
    ]
    json_path, md_path = run_eval(
        _guardrail_wrapped_stub_agent, golden_records, output_dir, run_label="e2e_smoke"
    )
    summary["eval_json_report"] = json_path
    summary["eval_md_report"] = md_path

    return summary
