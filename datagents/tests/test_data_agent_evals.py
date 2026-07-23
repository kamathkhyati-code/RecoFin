"""A15: data-agent evals -- labeled fixtures for validation/normalization
wired into C's eval harness, reports must meet accuracy/exactness targets.
"""
from __future__ import annotations

import json
import os
import tempfile

from datagents.eval.fixtures import build_normalization_fixtures, build_validation_fixtures
from datagents.eval.run_data_agent_evals import (
    NORMALIZATION_EXACTNESS_TARGET,
    VALIDATION_ACCURACY_TARGET,
    run_data_agent_evals,
)


def test_validation_fixtures_cover_every_reachable_reason_code():
    labels = {r.expected_label for r in build_validation_fixtures()}
    assert labels == {"OK", "MISSING_FIELD", "DUPLICATE_TXN", "NON_POSITIVE_AMOUNT", "AMBIGUOUS"}


def test_normalization_fixtures_are_internally_consistent_json():
    for record in build_normalization_fixtures():
        json.loads(record.expected_label)  # must not raise


def test_run_data_agent_evals_writes_both_reports_and_meets_targets():
    with tempfile.TemporaryDirectory() as tmp:
        result = run_data_agent_evals(tmp)

        assert os.path.exists(result["validation"]["report_json"])
        assert os.path.exists(result["validation"]["report_md"])
        assert os.path.exists(result["normalization"]["report_json"])
        assert os.path.exists(result["normalization"]["report_md"])

        assert result["validation"]["accuracy"] >= VALIDATION_ACCURACY_TARGET
        assert result["validation"]["meets_target"] is True

        assert result["normalization"]["exactness"] >= NORMALIZATION_EXACTNESS_TARGET
        assert result["normalization"]["meets_target"] is True


def test_validation_eval_report_reflects_perfect_accuracy_on_these_fixtures():
    """The fixtures are deterministic and the deterministic tools are
    already independently unit-tested (test_validation.py) -- so a
    non-1.0 accuracy here would mean this eval's own agent_fn or fixture
    data disagrees with the real validate_transactions behavior, not
    normal noise to tolerate.
    """
    with tempfile.TemporaryDirectory() as tmp:
        result = run_data_agent_evals(tmp)
        assert result["validation"]["accuracy"] == 1.0
        assert result["normalization"]["exactness"] == 1.0
