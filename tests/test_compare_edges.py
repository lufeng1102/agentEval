import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from cli import app
from compare import compare_runs


def _write_report(path: Path, pass_rate: float = 1.0, avg_score: float = 1.0, results: list[dict] | None = None) -> None:
    path.mkdir(parents=True, exist_ok=True)
    payload = {
        "summary": {
            "pass_rate": pass_rate,
            "avg_score": avg_score,
            "latency_ms": {"p50": 100, "p95": 200},
            "usage": {"total_input_tokens": 10, "output_tokens": 5},
        },
        "results": results or [],
    }
    (path / "report.json").write_text(json.dumps(payload), encoding="utf-8")


def test_compare_runs_raises_when_report_is_missing(tmp_path: Path) -> None:
    baseline = tmp_path / "baseline"
    candidate = tmp_path / "candidate"
    _write_report(baseline)
    candidate.mkdir()

    with pytest.raises(FileNotFoundError, match="report.json not found"):
        compare_runs(baseline, candidate)


def test_compare_runs_raises_when_report_json_is_invalid(tmp_path: Path) -> None:
    baseline = tmp_path / "baseline"
    candidate = tmp_path / "candidate"
    _write_report(baseline)
    candidate.mkdir()
    (candidate / "report.json").write_text("{bad json", encoding="utf-8")

    with pytest.raises(json.JSONDecodeError):
        compare_runs(baseline, candidate)


def test_compare_runs_tracks_added_and_removed_result_pairs(tmp_path: Path) -> None:
    baseline = tmp_path / "baseline"
    candidate = tmp_path / "candidate"
    _write_report(
        baseline,
        results=[
            {"case_id": "removed", "evaluator": "contains", "passed": False},
            {"case_id": "stable", "evaluator": "contains", "passed": False},
        ],
    )
    _write_report(
        candidate,
        results=[
            {"case_id": "added", "evaluator": "contains", "passed": False},
            {"case_id": "stable", "evaluator": "contains", "passed": True},
        ],
    )

    comparison = compare_runs(baseline, candidate)

    assert comparison["newly_failed"] == ["added::contains"]
    assert comparison["newly_passed"] == ["removed::contains", "stable::contains"]


def test_cli_compare_supports_md_format_alias(tmp_path: Path) -> None:
    baseline = tmp_path / "baseline"
    candidate = tmp_path / "candidate"
    _write_report(baseline)
    _write_report(candidate)
    runner = CliRunner()

    result = runner.invoke(app, ["compare", "--baseline", str(baseline), "--candidate", str(candidate), "--out", str(tmp_path / "compare.md"), "--format", "md"])

    assert result.exit_code == 0, result.output
    assert (tmp_path / "compare.md").exists()
    assert "AgentEval Compare Report" in (tmp_path / "compare.md").read_text(encoding="utf-8")


def test_cli_compare_rejects_unsupported_format(tmp_path: Path) -> None:
    baseline = tmp_path / "baseline"
    candidate = tmp_path / "candidate"
    _write_report(baseline)
    _write_report(candidate)
    runner = CliRunner()

    result = runner.invoke(app, ["compare", "--baseline", str(baseline), "--candidate", str(candidate), "--out", str(tmp_path / "compare.txt"), "--format", "txt"])

    assert result.exit_code != 0
    assert "unsupported compare format: txt" in result.output
