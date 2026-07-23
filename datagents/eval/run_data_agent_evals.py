"""A15: run the validation and normalization agents against labeled
fixtures through C's eval harness, write reports, check against targets.

Kept as a plain callable (run_data_agent_evals) rather than a script-only
entry point, so tests can call it directly and assert on the returned
metrics without shelling out or parsing report files.
"""
from __future__ import annotations

import json
from datetime import date
from decimal import Decimal

from datagents.eval.fixtures import build_normalization_fixtures, build_validation_fixtures
from datagents.schemas import Currency, Transaction
from datagents.tools.normalization_tools import canonicalize_reference, entity_alias_tool, fx_rate_tool
from datagents.agents.validation_agent import validate_transactions
from recon_platform.eval.harness import run_eval
from recon_platform.gateway.llm_gateway import MockLLMGateway

VALIDATION_ACCURACY_TARGET = 0.9
NORMALIZATION_EXACTNESS_TARGET = 0.9


def _txn_from_dict(d: dict) -> Transaction:
    return Transaction(
        txn_id=d["txn_id"],
        date=date.fromisoformat(d["date"]),
        amount=Decimal(d["amount"]),
        currency=d["currency"],
        counterparty=d["counterparty"],
        reference=d.get("reference"),
        source="csv",
    )


def _validation_agent_fn(input_dict: dict) -> str:
    """Reconstruct the batch, run the real validation checks, return the
    subject transaction's single reason code (or "OK" if clean).
    """
    txns = [_txn_from_dict(d) for d in input_dict["batch"]]
    gateway = (
        MockLLMGateway('{"verdict": "review", "confidence": 0.2, "reason": "no reference to anchor it"}')
        if input_dict.get("use_mock_gateway")
        else None
    )
    findings = validate_transactions(txns, gateway=gateway)
    subject_id = input_dict["subject_txn_id"]
    for f in findings:
        if f.txn_id == subject_id:
            return f.reason.value
    return "OK"


def _normalization_agent_fn(input_dict: dict) -> str:
    """Run the real normalization tools (no gateway/store -- deterministic,
    reproducible) and return the serialized result for exact-match scoring.
    """
    txn = _txn_from_dict(input_dict)
    normalized = {
        "amount": str(fx_rate_tool(txn.amount, txn.currency, base=Currency.USD)),
        "currency": Currency.USD.value,
        "counterparty": entity_alias_tool(txn.counterparty, gateway=None, store=None),
        "reference": canonicalize_reference(txn.reference),
    }
    return json.dumps(normalized)


def run_data_agent_evals(output_dir: str) -> dict:
    """Run both evals, write reports, return a summary dict with metrics
    and whether each met its target -- the acceptance criterion this task
    is actually graded on.
    """
    val_json, val_md = run_eval(
        _validation_agent_fn,
        build_validation_fixtures(),
        output_dir,
        positive_label="OK",
        run_label="a15_validation_eval",
    )
    norm_json, norm_md = run_eval(
        _normalization_agent_fn,
        build_normalization_fixtures(),
        output_dir,
        positive_label=build_normalization_fixtures()[0].expected_label,
        run_label="a15_normalization_eval",
    )

    with open(val_json) as f:
        val_metrics = json.load(f)["metrics"]
    with open(norm_json) as f:
        norm_metrics = json.load(f)["metrics"]

    return {
        "validation": {
            "report_json": val_json,
            "report_md": val_md,
            "accuracy": val_metrics["accuracy"],
            "meets_target": val_metrics["accuracy"] >= VALIDATION_ACCURACY_TARGET,
        },
        "normalization": {
            "report_json": norm_json,
            "report_md": norm_md,
            "exactness": norm_metrics["accuracy"],
            "meets_target": norm_metrics["accuracy"] >= NORMALIZATION_EXACTNESS_TARGET,
        },
    }
