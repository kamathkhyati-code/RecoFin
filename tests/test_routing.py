from recon_platform.graph.routing import validation_gate, matched_gate, close_ready_gate


class FakeIssue:
    def __init__(self, severity, row_ref=None):
        self.severity = severity
        self.row_ref = row_ref


def test_validation_gate_no_issues_proceeds():
    state = {"issues": [], "retry_count": 0}
    assert validation_gate(state) == "normalization"


def test_validation_gate_non_critical_issue_proceeds():
    state = {"issues": [FakeIssue("warning")], "retry_count": 0}
    assert validation_gate(state) == "normalization"


def test_validation_gate_retries_when_critical_issue_and_retries_remain():
    state = {"issues": [FakeIssue("error")], "retry_count": 0}
    assert validation_gate(state) == "ingestion"


def test_validation_gate_escalates_when_retries_exhausted():
    state = {"issues": [FakeIssue("error")], "retry_count": 2}
    assert validation_gate(state) == "resolution"


def test_validation_gate_row_level_error_does_not_block():
    """A single malformed row (row_ref set) is expected noise, not fatal."""
    state = {"issues": [FakeIssue("error", row_ref="row-42")], "retry_count": 0}
    assert validation_gate(state) == "normalization"


def test_validation_gate_row_level_errors_mixed_with_warnings_still_proceeds():
    state = {
        "issues": [
            FakeIssue("error", row_ref="row-1"),
            FakeIssue("warning", row_ref="row-2"),
            FakeIssue("error", row_ref="row-3"),
        ],
        "retry_count": 0,
    }
    assert validation_gate(state) == "normalization"


def test_validation_gate_batch_level_error_still_blocks():
    """No row_ref means a systemic failure (e.g. source unreachable) -- still blocks."""
    state = {"issues": [FakeIssue("error", row_ref=None)], "retry_count": 0}
    assert validation_gate(state) == "ingestion"


def test_matched_gate_routes_unmatched_to_resolution():
    state = {"unmatched_count": 3}
    assert matched_gate(state) == "resolution"


def test_matched_gate_routes_fully_matched_to_consolidation():
    state = {"unmatched_count": 0}
    assert matched_gate(state) == "consolidation"


def test_close_ready_gate_routes_ready_to_learning():
    state = {"close_ready": True}
    assert close_ready_gate(state) == "learning"


def test_close_ready_gate_routes_not_ready_to_end():
    state = {"close_ready": False}
    assert close_ready_gate(state) == "end"
