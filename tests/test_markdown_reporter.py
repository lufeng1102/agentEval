from pathlib import Path

from reporters.markdown_reporter import write_markdown_report
from schemas import AgentRun, EvalCase, EvalResult, Usage


def test_markdown_reporter_writes_summary_errors_and_failures(tmp_path: Path) -> None:
    path = tmp_path / "report.md"
    cases = [EvalCase(id="c1", input="q", tags=["safety"])]
    runs = [AgentRun(case_id="c1", final_output="bad", errors=["adapter failed"], usage=Usage(input_tokens=1, output_tokens=2))]
    results = [EvalResult(case_id="c1", evaluator="contains", score=0.25, passed=False, failure_reason="missing fact")]

    write_markdown_report(path, cases, runs, results)

    content = path.read_text(encoding="utf-8")
    assert "# AgentEval Report" in content
    assert "- Cases: 1" in content
    assert "| contains | 1 | 0.00% | 0.25 |" in content
    assert "| safety | 1 | 0.00% | 0.25 |" in content
    assert "- `c1`: adapter failed" in content
    assert "### c1 / contains" in content
    assert "- Reason: missing fact" in content


def test_markdown_reporter_handles_empty_results(tmp_path: Path) -> None:
    path = tmp_path / "report.md"

    write_markdown_report(path, [], [], [])

    content = path.read_text(encoding="utf-8")
    assert "- Cases: 0" in content
    assert "- Evaluation results: 0" in content
    assert "No run errors." in content
    assert "No evaluation failures." in content
