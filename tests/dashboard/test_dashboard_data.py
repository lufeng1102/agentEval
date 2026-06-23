from __future__ import annotations

import json
from pathlib import Path

from dashboard import CaseFilters, LocalRunDataSource
from schemas import AgentRun, ChatMessage, EvalResult, ToolCall, TraceSpan, Usage


def write_run(path: Path, *, pass_rate: float = 0.5) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    (path / "manifest.json").write_text(json.dumps({"run_id": path.name}), encoding="utf-8")
    report = {
        "summary": {"pass_rate": pass_rate, "avg_score": 0.75},
        "cases": [
            {"id": "c1", "name": "Case 1", "input": "q1", "expected": {"answer": "a1"}, "tags": ["smoke"], "metadata": {"risk_level": "low", "capability": "qa"}},
            {"id": "c2", "name": "Case 2", "input": "q2", "expected": {"answer": "a2"}, "tags": ["regression"], "metadata": {"risk_level": "high", "capability": "tool_use"}},
        ],
        "runs": [],
        "results": [],
    }
    (path / "report.json").write_text(json.dumps(report), encoding="utf-8")
    runs = [
        AgentRun(
            case_id="c1",
            messages=[ChatMessage(role="user", content="q1")],
            final_output="a1",
            spans=[TraceSpan(span_id="root", trace_id="trace-c1", name="agent.run", kind="agent"), TraceSpan(span_id="tool", trace_id="trace-c1", parent_span_id="root", name="search", kind="tool", latency_ms=10)],
            tool_calls=[ToolCall(name="search", input={"q": "q1"}, output={"hits": 1})],
            usage=Usage(input_tokens=3, output_tokens=4),
            latency_ms=20,
            raw_response={"trace_id": "trace-c1"},
        ),
        AgentRun(case_id="c2", final_output="bad", errors=["boom"], latency_ms=40),
    ]
    results = [
        EvalResult(case_id="c1", evaluator="contains", score=1.0, passed=True),
        EvalResult(case_id="c2", evaluator="contains", score=0.0, passed=False, failure_reason="missing answer"),
    ]
    (path / "traces.jsonl").write_text("".join(run.model_dump_json() + "\n" for run in runs), encoding="utf-8")
    (path / "results.jsonl").write_text("".join(result.model_dump_json() + "\n" for result in results), encoding="utf-8")
    return path


def test_local_run_summary(tmp_path: Path) -> None:
    source = LocalRunDataSource(write_run(tmp_path / "candidate"))

    summary = source.get_run_summary()

    assert summary.run_id == "candidate"
    assert summary.case_count == 2
    assert summary.result_count == 2
    assert summary.pass_rate == 0.5
    assert summary.failed_case_count == 1
    assert summary.error_count == 1
    assert summary.total_tool_calls == 1
    assert summary.total_input_tokens == 3
    assert summary.total_output_tokens == 4


def test_list_cases_and_filters(tmp_path: Path) -> None:
    source = LocalRunDataSource(write_run(tmp_path / "candidate"))

    page = source.list_cases(filters=CaseFilters(status="failed"))

    assert page.total == 1
    assert page.items[0].case_id == "c2"
    assert page.items[0].failed_evaluators == ["contains"]

    high_risk = source.list_cases(filters=CaseFilters(risk_level="high", capability="tool_use"))
    assert high_risk.total == 1
    assert high_risk.items[0].case_id == "c2"


def test_case_detail_includes_run_results_and_trace(tmp_path: Path) -> None:
    source = LocalRunDataSource(write_run(tmp_path / "candidate"))

    detail = source.get_case_detail("latest", "c1")

    assert detail.case["input"] == "q1"
    assert detail.run is not None
    assert detail.run.final_output == "a1"
    assert detail.results[0].evaluator == "contains"
    assert detail.trace is not None
    assert detail.trace.trace_id == "trace-c1"


def test_trace_view_builds_parent_child_depths(tmp_path: Path) -> None:
    source = LocalRunDataSource(write_run(tmp_path / "candidate"))

    trace = source.get_trace("latest", "c1")

    assert trace.root_span_id == "root"
    assert trace.span_count == 2
    assert trace.tool_call_count == 1
    assert [(row.span_id, row.depth) for row in trace.flat_spans] == [("root", 0), ("tool", 1)]


def test_pagination(tmp_path: Path) -> None:
    source = LocalRunDataSource(write_run(tmp_path / "candidate"))

    page = source.list_cases(page=2, page_size=1)

    assert page.total == 2
    assert page.page == 2
    assert len(page.items) == 1
    assert page.items[0].case_id == "c2"


def test_compare_to_uses_existing_compare_helper(tmp_path: Path) -> None:
    baseline = write_run(tmp_path / "baseline", pass_rate=1.0)
    candidate = write_run(tmp_path / "candidate", pass_rate=0.5)

    comparison = LocalRunDataSource(candidate).compare_to(baseline)

    assert comparison["delta"]["pass_rate"] == -0.5
