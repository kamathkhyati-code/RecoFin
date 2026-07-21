from recon_platform.graph.build import build_graph
from recon_platform.state import IssueRecord, ReconState


def test_graph_compiles():
    graph = build_graph()
    assert graph is not None


def test_graph_happy_path_dry_run():
    graph = build_graph()
    initial_state: ReconState = {
        "run_id": "test-run",
        "period": "2026-06",
        "messages": [],
        "issues": [],
        "matched_count": 10,
        "unmatched_count": 0,
        "close_ready": True,
    }
    result = graph.invoke(initial_state)

    role_values = [m.role.value for m in result["messages"]]
    assert "supervisor" in role_values
    assert "ingestion" in role_values
    assert "validation" in role_values
    assert "normalization" in role_values
    assert "matching" in role_values
    assert "consolidation" in role_values
    assert "learning" in role_values
    assert "resolution" not in role_values


def test_persistent_critical_issue_escalates_instead_of_looping_forever():
    """A batch-level (row_ref=None) issue is genuinely critical and should
    retry ingestion up to MAX_VALIDATION_RETRIES times, then escalate to
    resolution -- not loop ingestion<->validation forever or hit
    LangGraph's recursion limit. Regression test for a bug flagged by
    Intern A: nothing incremented retry_count, so validation_gate always
    saw retry_count=0 and never stopped retrying.
    """
    graph = build_graph()
    initial_state: ReconState = {
        "run_id": "retry-loop-test",
        "period": "2026-06",
        "messages": [],
        "issues": [IssueRecord(source="ingestion", severity="error", message="source unreachable")],
        "matched_count": 0,
        "unmatched_count": 0,
        "close_ready": True,
    }

    result = graph.invoke(initial_state, config={"recursion_limit": 25})

    role_values = [m.role.value for m in result["messages"]]
    assert "resolution" in role_values
    assert "normalization" not in role_values
    ingestion_attempts = role_values.count("ingestion")
    # ingestion_node increments retry_count before the gate reads it, so
    # attempt 1 -> retry_count=1 (1<2, retry) -> attempt 2 -> retry_count=2
    # (2<2 is False, escalate). MAX_VALIDATION_RETRIES=2 total attempts.
    assert ingestion_attempts == 2
