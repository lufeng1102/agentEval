from __future__ import annotations

import json
from pathlib import Path

from typer.testing import CliRunner

from cli import app
from exports import export_run, load_export_bundle, validate_records
from exports.langfuse import export_records as export_langfuse
from schemas import AgentRun, ChatMessage, EvalResult, ToolCall, TraceSpan


def write_fixture(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    (path / "manifest.json").write_text(json.dumps({"run_id": "run-1", "agent": {"provider": "static"}}), encoding="utf-8")
    (path / "report.json").write_text(
        json.dumps(
            {
                "summary": {"pass_rate": 1.0, "avg_score": 0.9},
                "cases": [{"id": "c1", "input": "question", "expected": {"answer": "answer"}, "tags": ["p3"]}],
                "runs": [],
                "results": [],
            }
        ),
        encoding="utf-8",
    )
    run = AgentRun(
        case_id="c1",
        messages=[ChatMessage(role="user", content="question")],
        final_output="answer",
        tool_calls=[ToolCall(name="search", input={"query": "question"}, output={"hits": 1})],
        spans=[TraceSpan(span_id="root", trace_id="trace-c1", name="agent.run", kind="agent"), TraceSpan(span_id="llm", trace_id="trace-c1", parent_span_id="root", name="llm.generate", kind="llm", output={"text": "answer"})],
        raw_response={"trace_id": "trace-c1"},
    )
    result = EvalResult(case_id="c1", evaluator="contains", score=1.0, passed=True)
    (path / "traces.jsonl").write_text(run.model_dump_json() + "\n", encoding="utf-8")
    (path / "results.jsonl").write_text(result.model_dump_json() + "\n", encoding="utf-8")
    return path


def read_jsonl(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def test_load_export_bundle(tmp_path: Path) -> None:
    run_dir = write_fixture(tmp_path / "run")

    bundle = load_export_bundle(run_dir)

    assert bundle.run_id == "run-1"
    assert bundle.runs[0].case_id == "c1"
    assert bundle.results[0].evaluator == "contains"


def test_langfuse_export_records_include_observations_and_scores(tmp_path: Path) -> None:
    bundle = load_export_bundle(write_fixture(tmp_path / "run"))

    records = list(export_langfuse(bundle))

    assert records[0]["id"] == "trace-c1"
    assert records[0]["observations"][0]["id"] == "root"
    assert records[0]["scores"][0]["name"] == "contains"


def test_export_run_writes_all_targets(tmp_path: Path) -> None:
    run_dir = write_fixture(tmp_path / "run")

    for target in ["langfuse", "phoenix", "braintrust"]:
        out = tmp_path / f"{target}.jsonl"
        issues = export_run(target, run_dir, out, validate=True)
        assert [issue for issue in issues if issue.severity == "error"] == []
        records = read_jsonl(out)
        assert records

    assert read_jsonl(tmp_path / "phoenix.jsonl")[0]["context"]["trace_id"] == "trace-c1"
    assert read_jsonl(tmp_path / "braintrust.jsonl")[0]["scores"] == {"contains": 1.0}


def test_synthetic_tool_span_when_run_has_tool_calls_without_spans(tmp_path: Path) -> None:
    run_dir = write_fixture(tmp_path / "run")
    run = AgentRun(case_id="c1", final_output="answer", tool_calls=[ToolCall(name="search", input={"q": "x"})])
    (run_dir / "traces.jsonl").write_text(run.model_dump_json() + "\n", encoding="utf-8")

    export_run("langfuse", run_dir, tmp_path / "langfuse.jsonl", validate=True)

    record = read_jsonl(tmp_path / "langfuse.jsonl")[0]
    assert record["observations"][0]["id"].startswith("synthetic_tool_c1_0_0")
    assert record["observations"][0]["type"] == "TOOL"


def test_validate_records_reports_missing_required_fields() -> None:
    issues = validate_records("phoenix", [{"context": {}, "attributes": {}}])

    assert {issue.path for issue in issues if issue.severity == "error"} == {"records[0].context.trace_id", "records[0].context.span_id", "records[0].name"}


def test_cli_export_command(tmp_path: Path) -> None:
    run_dir = write_fixture(tmp_path / "run")
    out = tmp_path / "langfuse.jsonl"

    result = CliRunner().invoke(app, ["export", "langfuse", "--run", str(run_dir), "--out", str(out), "--validate"])

    assert result.exit_code == 0
    assert "Exported langfuse" in result.output
    assert read_jsonl(out)
