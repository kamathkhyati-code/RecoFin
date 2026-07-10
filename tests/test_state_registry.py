from recon_platform.state import ReconState
from recon_platform.registry import registry


def test_recon_state_importable():
    state: ReconState = {"run_id": "r1", "period": "2026-06", "messages": []}
    assert state["run_id"] == "r1"


def test_registry_has_dummy_tool():
    assert "dummy_echo_tool" in registry.list_tools()
    tool = registry.get("dummy_echo_tool")
    assert tool.func("hello") == "hello"
