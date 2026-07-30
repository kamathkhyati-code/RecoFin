"""C19: bug bash -- regression tests for defects found and fixed during
the bash. See docs/BUG_BASH.md for the full triage board.
"""

from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal

from datagents.schemas import Currency, SourceType, Transaction
from recon_platform.gateway.llm_gateway import MockLLMGateway
from recon_platform.graph.build import build_graph


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


def test_gateway_is_reachable_through_real_graph():
    """Defect: build_graph() never wired a gateway into validation_node/
    normalization_node/matching_node, so every LLM-escalation feature
    (B5 semantic matching, A6/A7 ambiguous-row fallback, A9 entity alias
    resolution) was silently dead code in production despite being built
    and tested standalone. Fixed by threading gateway through
    functools.partial when registering the three nodes.

    Uses a uuid-suffixed counterparty name so this can never coincide
    with an entry AliasStore's on-disk cache already has from an earlier
    run -- that cache is real, persistent, cross-process state by design
    (A9: a 2nd run should make zero LLM calls), and a fixed name here
    would make this test's outcome depend on ambient disk state, exactly
    the flakiness found by hand while bug-bashing this fix.
    """
    unique_name = f"Unknown Corp {uuid.uuid4()}"
    book = [_txn("B1", "100.00", unique_name, "INV-1")]
    source = [_txn("S1", "100.00", unique_name, "INV-1", source=SourceType.API)]

    gateway = MockLLMGateway(canned_response="RESOLVED_BY_LLM")
    graph = build_graph(gateway=gateway)
    graph.invoke(
        {
            "run_id": "c19-gateway-test",
            "period": "2026-06",
            "messages": [],
            "issues": [],
            "book_transactions": book,
            "source_transactions": source,
        }
    )

    assert gateway.usage.calls > 0


def test_no_gateway_still_works_fully_deterministic():
    """The fix must not change default behavior: omitting gateway still
    means zero LLM calls, matching every existing caller's expectation."""
    book = [_txn("B1", "100.00", "ACME", "INV-1")]
    source = [_txn("S1", "100.00", "ACME", "INV-1", source=SourceType.API)]

    graph = build_graph()
    result = graph.invoke(
        {
            "run_id": "c19-no-gateway-test",
            "period": "2026-06",
            "messages": [],
            "issues": [],
            "book_transactions": book,
            "source_transactions": source,
        }
    )

    assert result["report"].matched_count == 1
