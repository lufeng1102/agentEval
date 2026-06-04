from pathlib import Path

from reporters.html_reporter import write_html_report, write_html_report_from_json
from schemas import AgentRun, EvalCase, EvalResult, ToolCall, Usage


def test_html_reporter_writes_summary_and_failures(tmp_path: Path) -> None:
    path = tmp_path / "report.html"
    cases = [EvalCase(id="c1", input="q", name="Case One")]
    runs = [AgentRun(case_id="c1", final_output="hello")]
    results = [EvalResult(case_id="c1", evaluator="contains", score=0, passed=False, failure_reason="missing fact")]

    write_html_report(path, cases, runs, results)

    content = path.read_text(encoding="utf-8")
    assert "AgentEval Report" in content
    assert "By Evaluator" in content
    assert "missing fact" in content
    assert "hello" in content


def test_html_reporter_converts_json_payload(tmp_path: Path) -> None:
    path = tmp_path / "report.html"
    payload = {
        "summary": {
            "cases": 1,
            "failures": 1,
            "pass_rate": 0.0,
            "avg_score": 0.0,
            "usage": {"cache_hit_rate": 0.0},
            "by_evaluator": {"contains": {"results": 1, "pass_rate": 0.0, "avg_score": 0.0}},
            "by_tag": {},
            "errors": {"by_case": {}},
        },
        "runs": [{"case_id": "c1", "final_output": "hello from json"}],
        "results": [{"case_id": "c1", "evaluator": "contains", "score": 0, "passed": False, "failure_reason": "missing fact"}],
    }

    write_html_report_from_json(path, payload)

    content = path.read_text(encoding="utf-8")
    assert "AgentEval Report" in content
    assert "Evaluation Report" in content
    assert "Needs attention" in content
    assert "Failed" in content
    assert "c1" in content
    assert "hello from json" in content
    assert "contains" in content
    assert "missing fact" in content


def test_html_reporter_creates_parent_directories(tmp_path: Path) -> None:
    path = tmp_path / "nested" / "reports" / "report.html"

    write_html_report(path, [EvalCase(id="c1", input="q")], [AgentRun(case_id="c1")], [])

    assert path.exists()


def test_html_reporter_uses_cases_from_json_payload(tmp_path: Path) -> None:
    path = tmp_path / "report.html"
    payload = {
        "cases": [{"id": "c1", "name": "Case One", "tags": ["safety"]}],
        "summary": {
            "cases": 1,
            "failures": 0,
            "pass_rate": 1.0,
            "avg_score": 1.0,
            "usage": {"cache_hit_rate": 0.0},
            "by_evaluator": {},
            "by_tag": {"safety": {"results": 1, "pass_rate": 1.0, "avg_score": 1.0}},
            "errors": {"by_case": {}},
        },
        "runs": [{"case_id": "c1", "final_output": "safe"}],
        "results": [{"case_id": "c1", "evaluator": "safety", "score": 1, "passed": True}],
    }

    write_html_report_from_json(path, payload)

    content = path.read_text(encoding="utf-8")
    assert "Case One" in content
    assert "safety" in content


def test_html_reporter_summarizes_json_payload_without_summary(tmp_path: Path) -> None:
    path = tmp_path / "report.html"
    payload = {
        "runs": [
            {
                "case_id": "c1",
                "final_output": "ok",
                "tool_calls": [{"name": "lookup", "input": {"id": "A100"}, "output": {"status": "paid"}}],
                "usage": {"output_tokens": 7},
            }
        ],
        "results": [{"case_id": "c1", "evaluator": "contains", "score": 1, "passed": True}],
    }

    write_html_report_from_json(path, payload)

    content = path.read_text(encoding="utf-8")
    assert "100.00%" in content
    assert "Passing" in content
    assert "Tool calls" in content
    assert "lookup" in content
    assert "Output tokens" in content
