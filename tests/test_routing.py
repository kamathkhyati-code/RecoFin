from recon_platform.graph.routing import validation_gate, matched_gate, close_ready_gate


class FakeIssue:
    def __init__(self, severity):
        self.severity = severity


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
