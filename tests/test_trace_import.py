import json

from schemas import AgentTrace
from traces.normalize import agent_trace_to_case, agent_trace_to_run, normalize_trace_payloads, production_events_to_traces
from production.ingest import load_production_events


def test_production_event_normalizes_to_trace(tmp_path) -> None:
    events = tmp_path / "events.jsonl"
    events.write_text(json.dumps({"event_id": "e1", "trace_id": "t1", "input": "refund", "final_output": "done", "tool_calls": [{"name": "lookup", "input": {"id": "1"}, "output": {"ok": True}}]}) + "\n", encoding="utf-8")

    traces = production_events_to_traces(load_production_events(events))

    assert traces[0].trace_id == "t1"
    assert traces[0].tool_calls[0].name == "lookup"
    assert traces[0].spans[0].kind == "tool"


def test_otel_spans_group_by_trace_id(tmp_path) -> None:
    spans = tmp_path / "spans.jsonl"
    spans.write_text("\n".join([json.dumps({"trace_id": "t1", "span_id": "s1", "name": "agent", "attributes": {"openinference.span.kind": "AGENT"}}), json.dumps({"trace_id": "t1", "span_id": "s2", "name": "search", "kind": "tool", "status": "error", "error": "boom"})]) + "\n", encoding="utf-8")

    traces = normalize_trace_payloads(spans, source="otel")

    assert len(traces) == 1
    assert [span.name for span in traces[0].spans] == ["agent", "search"]
    assert traces[0].errors == ["boom"]


def test_trace_converts_to_case_and_run() -> None:
    trace = AgentTrace(trace_id="t1", source="agenteval", input="hello", final_output="world")

    case = agent_trace_to_case(trace)
    run = agent_trace_to_run(trace)

    assert case.id == "trace_t1"
    assert case.input == "hello"
    assert run.case_id == "trace_t1"
    assert run.final_output == "world"
