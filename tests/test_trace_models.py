from schemas import AgentRun, AgentTrace, TraceSpan


def test_agent_run_accepts_missing_spans_for_backward_compatibility() -> None:
    run = AgentRun.model_validate({"case_id": "c1", "final_output": "ok"})

    assert run.spans == []
    assert run.model_dump(mode="json")["spans"] == []


def test_agent_trace_serializes_spans() -> None:
    trace = AgentTrace(
        trace_id="t1",
        source="otel",
        spans=[TraceSpan(span_id="s1", trace_id="t1", name="search", kind="tool", status="ok")],
    )

    payload = trace.model_dump(mode="json")

    assert payload["trace_id"] == "t1"
    assert payload["spans"][0]["name"] == "search"
