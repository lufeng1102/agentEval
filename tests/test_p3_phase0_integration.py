from __future__ import annotations

import json
from pathlib import Path

from typer.testing import CliRunner

from cli import app
from dashboard import LocalRunDataSource
from exports import export_run
from hosted import HostedIngestionService, LocalHostedStorage
from schemas import AgentRun, EvalResult


def write_standard_run(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    (path / "manifest.json").write_text(json.dumps({"run_id": "integration-run", "agent": {"provider": "static"}}), encoding="utf-8")
    (path / "report.json").write_text(
        json.dumps(
            {
                "summary": {"pass_rate": 1.0, "avg_score": 1.0},
                "cases": [{"id": "c1", "input": "q", "expected": {"answer": "a"}, "tags": ["integration"]}],
                "runs": [],
                "results": [],
            }
        ),
        encoding="utf-8",
    )
    (path / "traces.jsonl").write_text(AgentRun(case_id="c1", final_output="a").model_dump_json() + "\n", encoding="utf-8")
    (path / "results.jsonl").write_text(EvalResult(case_id="c1", evaluator="contains", score=1.0, passed=True).model_dump_json() + "\n", encoding="utf-8")
    return path


def read_jsonl(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def test_standard_artifacts_feed_dashboard_export_and_hosted_ingestion(tmp_path: Path) -> None:
    run_dir = write_standard_run(tmp_path / "run")

    summary = LocalRunDataSource(run_dir).get_run_summary()
    assert summary.run_id == "integration-run"
    assert summary.case_count == 1

    export_out = tmp_path / "braintrust.jsonl"
    issues = export_run("braintrust", run_dir, export_out, validate=True)
    assert [issue for issue in issues if issue.severity == "error"] == []
    assert read_jsonl(export_out)[0]["scores"] == {"contains": 1.0}

    service = HostedIngestionService(LocalHostedStorage(tmp_path / "hosted"))
    ingestion = service.ingest_run_directory(run_dir, project_id="proj")
    assert ingestion.status == "indexed"
    assert service.get_run(ingestion.run_id) is not None


def test_cli_upload_indexes_run(tmp_path: Path) -> None:
    run_dir = write_standard_run(tmp_path / "run")
    storage = tmp_path / "hosted"

    result = CliRunner().invoke(app, ["upload", "--run", str(run_dir), "--storage", str(storage), "--project-id", "proj", "--dashboard-base-url", "https://example"])

    assert result.exit_code == 0
    assert "Uploaded run_id=" in result.output
    assert "Dashboard: https://example/runs/" in result.output
    stored_runs = list((storage / "runs").glob("*.json"))
    assert len(stored_runs) == 1


def test_cli_upload_conflict_exits_nonzero(tmp_path: Path) -> None:
    first = write_standard_run(tmp_path / "first")
    second = write_standard_run(tmp_path / "second")
    (second / "traces.jsonl").write_text(AgentRun(case_id="c1", final_output="changed").model_dump_json() + "\n", encoding="utf-8")
    storage = tmp_path / "hosted"
    runner = CliRunner()

    first_result = runner.invoke(app, ["upload", "--run", str(first), "--storage", str(storage), "--project-id", "proj"])
    second_result = runner.invoke(app, ["upload", "--run", str(second), "--storage", str(storage), "--project-id", "proj"])

    assert first_result.exit_code == 0
    assert second_result.exit_code == 1
    assert "already exists with different artifacts" in second_result.output
