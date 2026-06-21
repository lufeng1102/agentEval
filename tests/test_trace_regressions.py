import json

import yaml

from traces.regressions import trace_failures_to_regressions


def test_error_trace_generates_regression(tmp_path) -> None:
    traces = tmp_path / "traces.jsonl"
    traces.write_text(json.dumps({"trace_id": "t1", "source": "otel", "input": "refund", "spans": [{"span_id": "s1", "trace_id": "t1", "name": "lookup", "kind": "tool", "status": "error", "error": "boom"}]}) + "\n", encoding="utf-8")

    dataset = trace_failures_to_regressions(traces)

    assert len(dataset["cases"]) == 1
    case = dataset["cases"][0]
    assert case["id"] == "trace_t1"
    assert "regression" in case["tags"]
    assert case["metadata"]["regression"]["fingerprint"]


def test_non_error_trace_skipped_when_only_errors(tmp_path) -> None:
    traces = tmp_path / "traces.jsonl"
    traces.write_text(json.dumps({"trace_id": "t1", "source": "otel", "input": "refund", "spans": [{"span_id": "s1", "trace_id": "t1", "name": "lookup", "kind": "tool", "status": "ok"}]}) + "\n", encoding="utf-8")

    dataset = trace_failures_to_regressions(traces, only_errors=True)

    assert dataset["cases"] == []
