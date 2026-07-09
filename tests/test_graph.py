from recon_platform.graph.build import build_graph
from recon_platform.state import ReconState


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
