"""Post-C20 integration audit: verify built capabilities are actually
reachable through the real compiled graph, not just exercised standalone
in their own unit tests. See docs/BUG_BASH.md-style precedent in
tests/test_c19_bug_bash.py (the gateway-wiring bug this audit followed up
on).
"""

from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal

import tempfile
import os

from datagents.schemas import Currency, SourceType, Transaction
from recon_platform.gateway.llm_gateway import MockLLMGateway
from recon_platform.graph.build import _MATCH_MEMORY, build_graph
from recon_platform.graph.checkpointer import get_checkpointer, run_pipeline


def _txn(txn_id, amount, counterparty, ref, source=SourceType.CSV):
    return Transaction(
        txn_id=txn_id,
        date=date(2026, 6, 1),
        amount=Decimal(amount),
        currency=Currency.USD,
        counterparty=counterparty,
        reference=ref,
        source=source,
    )


def test_match_memory_is_reachable_through_real_graph():
    """Defect: matching_node called run_match_subgraph without a `memory`
    kwarg, so B13's match memory (confirmed matches upserted, retrieval
    boosts confidence, memory grows from its own history -- Acceptance
    Checklist row 7) was built and tested standalone
    (reasoning/tests/test_match_memory.py, test_match_subgraph.py) but
    silently unreachable through the real graph, same class of bug as
    C19's dead gateway. Fixed by threading the module-level _MATCH_MEMORY
    singleton through matching_node.

    Proof: a pair run through the real graph should get upserted into
    _MATCH_MEMORY, provable by querying it directly afterward -- uuid
    counterparty so this can't coincide with another test's leftover
    entries in the shared in-process singleton.
    """
    unique_name = f"Audit Corp {uuid.uuid4()}"
    book = [_txn("B1", "100.00", unique_name, "INV-AUDIT-1")]
    source = [_txn("S1", "100.00", unique_name, "INV-AUDIT-1", source=SourceType.API)]

    graph = build_graph()
    result = graph.invoke(
        {
            "run_id": "audit-match-memory-test",
            "period": "2026-06",
            "messages": [],
            "issues": [],
            "book_transactions": book,
            "source_transactions": source,
        }
    )

    assert result["report"].matched_count == 1

    hits = _MATCH_MEMORY.retrieve_nearest(book[0], source[0], n_results=1)
    assert len(hits) == 1
    assert hits[0]["metadata"]["book_txn_id"] == "B1"
    assert hits[0]["metadata"]["source_txn_id"] == "S1"


def test_run_pipeline_gateway_is_reachable():
    """Defect: run_pipeline (the idempotent production entrypoint with
    skip-if-complete/resume-from-checkpoint semantics -- the one a real
    scheduler would call, per recon_platform/eval/metrics.py's usage)
    called build_graph(checkpointer=checkpointer) with no gateway param,
    so even after C19 fixed build_graph itself, anything routed through
    run_pipeline still never got a gateway. Fixed by adding gateway to
    run_pipeline's signature and forwarding it.
    """
    unique_name = f"Audit Pipeline Corp {uuid.uuid4()}"
    book = [_txn("B1", "100.00", unique_name, "INV-AUDIT-2")]
    source = [_txn("S1", "100.00", unique_name, "INV-AUDIT-2", source=SourceType.API)]

    gateway = MockLLMGateway(canned_response="RESOLVED_BY_LLM")

    with tempfile.TemporaryDirectory() as tmp:
        db_path = os.path.join(tmp, "checkpoints.db")
        with get_checkpointer(db_path) as cp:
            run_pipeline(
                period="2026-06",
                source_signature="audit-gateway-test",
                checkpointer=cp,
                initial_state={
                    "run_id": "audit-run-pipeline-gateway",
                    "period": "2026-06",
                    "messages": [],
                    "issues": [],
                    "book_transactions": book,
                    "source_transactions": source,
                },
                gateway=gateway,
            )

    assert gateway.usage.calls > 0
