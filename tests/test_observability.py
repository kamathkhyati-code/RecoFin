from recon_platform.graph.build import build_graph
from recon_platform.observability.tracer import GraphTracer
from recon_platform.observability.viewer import print_trace


def test_trace_tree_visible_for_full_run():
    tracer = GraphTracer()
    graph = build_graph()
    state = {
        "run_id": "trace-test-1",
        "period": "2026-06",
        "messages": [],
        "issues": [],
        "matched_count": 5,
        "unmatched_count": 0,
        "close_ready": True,
    }

    graph.invoke(state, config={"callbacks": [tracer]})

    node_names = {s.name for s in tracer.node_spans()}
    assert "supervisor" in node_names
    assert "consolidation" in node_names

    tree = tracer.trace_tree()
    assert len(tree) > 0

    for span in tracer.node_spans():
        assert span.duration_ms is not None
        assert span.duration_ms >= 0


def test_token_usage_and_trace_printing_do_not_error():
    tracer = GraphTracer()
    graph = build_graph()
    state = {
        "run_id": "trace-test-2",
        "period": "2026-06",
        "messages": [],
        "issues": [],
        "matched_count": 5,
        "unmatched_count": 0,
        "close_ready": True,
    }

    graph.invoke(state, config={"callbacks": [tracer]})

    assert tracer.total_tokens() == 0

    print_trace(tracer)
