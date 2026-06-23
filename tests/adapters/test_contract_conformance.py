from __future__ import annotations

from adapters.conformance import validate_agent_run_contract
from schemas import AgentRun, ToolCall, TraceSpan


def test_conformance_accepts_minimal_valid_run_with_adapter_metadata() -> None:
    run = AgentRun(
        case_id="case-1",
        final_output="ok",
        artifacts={
            "adapter": {
                "contract_version": "agenteval.adapter.v1",
                "adapter_name": "fake",
                "adapter_version": "0.1.0",
                "framework": "fake_framework",
                "capabilities": {"messages": True},
            }
        },
    )

    issues = validate_agent_run_contract(run)

    assert [item for item in issues if item.severity == "error"] == []


def test_conformance_warns_when_adapter_metadata_is_missing() -> None:
    run = AgentRun(case_id="case-1", final_output="ok")

    issues = validate_agent_run_contract(run)

    assert any(item.severity == "warning" and item.path == "artifacts.adapter" for item in issues)
    assert [item for item in issues if item.severity == "error"] == []


def test_conformance_reports_tool_span_and_raw_response_errors() -> None:
    run = AgentRun(
        case_id="case-1",
        final_output="ok",
        raw_response={"bad": object()},
        tool_calls=[ToolCall(name="", input={"query": "x"}, output=object())],
        spans=[TraceSpan(span_id="child", name="custom", kind="unknown", parent_span_id="missing")],
        artifacts={
            "adapter": {
                "contract_version": "wrong",
                "adapter_name": "fake",
                "adapter_version": "0.1.0",
                "framework": "fake_framework",
                "capabilities": {},
            }
        },
    )

    issues = validate_agent_run_contract(run)

    paths = {item.path for item in issues}
    assert "tool_calls[0].name" in paths
    assert "tool_calls[0].output" in paths
    assert "spans[0].kind" in paths
    assert "raw_response" in paths
    assert "spans[0].parent_span_id" in paths
    assert "artifacts.adapter.contract_version" in paths
