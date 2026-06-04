import json

from reporters.json_reporter import summarize, write_json_report
from schemas import AgentRun, EvalCase, EvalResult, ToolCall, Usage


def test_summarize_includes_evaluator_cache_tool_and_error_stats() -> None:
    cases = [EvalCase(id="c1", input="question", tags=["tool-use"])]
    runs = [
        AgentRun(
            case_id="c1",
            tool_calls=[ToolCall(name="weather"), ToolCall(name="broken", error="failed")],
            usage=Usage(input_tokens=10, output_tokens=5, cache_read_input_tokens=30),
            errors=["boom"],
        )
    ]
    results = [
        EvalResult(case_id="c1", evaluator="trajectory", score=1, passed=True),
        EvalResult(case_id="c1", evaluator="contains", score=0, passed=False, failure_type="missing_fact"),
    ]

    summary = summarize(cases, runs, results)

    assert summary["failures"] == 1
    assert summary["by_evaluator"]["trajectory"]["pass_rate"] == 1
    assert summary["by_evaluator"]["contains"]["pass_rate"] == 0
    assert summary["usage"]["total_input_tokens"] == 40
    assert summary["usage"]["cache_hit_rate"] == 0.75
    assert summary["tool_calls"] == {"total": 2, "failed": 1}
    assert summary["errors"]["total"] == 1
    assert summary["errors"]["by_case"] == {"c1": ["boom"]}
    assert summary["by_failure_type"]["missing_fact"]["results"] == 1
    assert "pass_at_1" in summary["stability"]


def test_json_report_includes_cases_for_later_visualization(tmp_path) -> None:
    path = tmp_path / "report.json"
    cases = [EvalCase(id="c1", input="question", name="Case One", tags=["safety"])]
    runs = [AgentRun(case_id="c1", final_output="ok")]
    results = [EvalResult(case_id="c1", evaluator="contains", score=1, passed=True)]

    write_json_report(path, cases, runs, results)

    payload = json.loads(path.read_text(encoding="utf-8"))
    assert payload["cases"][0]["id"] == "c1"
    assert payload["cases"][0]["name"] == "Case One"
    assert payload["cases"][0]["tags"] == ["safety"]
