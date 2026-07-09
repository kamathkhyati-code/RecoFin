from reasoning.agents.matching_agent import matching_agent
from recon_platform.state import ReconState


def test_matching_agent_stub_runs():
    state: ReconState = {
        "run_id": "test-run",
        "period": "2026-06",
        "messages": [],
    }
    result = matching_agent(state)
    assert "messages" in result
    assert len(result["messages"]) == 1
    assert result["messages"][0].role.value == "matching"
