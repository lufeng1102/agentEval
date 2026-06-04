import json
from pathlib import Path

from typer.testing import CliRunner

from cli import app
from compare import compare_runs, write_compare_markdown


def _write_report(path: Path, pass_rate: float, avg_score: float, results: list[dict]) -> None:
    path.mkdir(parents=True, exist_ok=True)
    payload = {
        "summary": {
            "pass_rate": pass_rate,
            "avg_score": avg_score,
            "latency_ms": {"p50": 100, "p95": 200},
            "usage": {"total_input_tokens": 10, "output_tokens": 5},
        },
        "results": results,
    }
    (path / "report.json").write_text(json.dumps(payload), encoding="utf-8")


def test_compare_runs_reports_deltas_and_status_changes(tmp_path: Path) -> None:
    baseline = tmp_path / "baseline"
    candidate = tmp_path / "candidate"
    _write_report(baseline, 0.5, 0.5, [{"case_id": "c1", "evaluator": "contains", "passed": False}])
    _write_report(candidate, 1.0, 0.8, [{"case_id": "c1", "evaluator": "contains", "passed": True}])

    comparison = compare_runs(baseline, candidate)

    assert comparison["delta"]["pass_rate"] == 0.5
    assert comparison["newly_passed"] == ["c1::contains"]
    assert comparison["newly_failed"] == []


def test_write_compare_markdown(tmp_path: Path) -> None:
    comparison = {
        "baseline": "base",
        "candidate": "cand",
        "delta": {"pass_rate": 0, "avg_score": 0, "latency_p50_ms": 0, "latency_p95_ms": 0, "total_tokens": 0},
        "newly_failed": ["c1::contains"],
        "newly_passed": [],
    }
    path = tmp_path / "compare.md"

    write_compare_markdown(path, comparison)

    assert "AgentEval Compare Report" in path.read_text(encoding="utf-8")


def test_cli_compare_threshold_passes_and_fails(tmp_path: Path) -> None:
    baseline = tmp_path / "baseline"
    candidate = tmp_path / "candidate"
    _write_report(baseline, 1.0, 1.0, [{"case_id": "c1", "evaluator": "contains", "passed": True}])
    _write_report(candidate, 0.9, 0.9, [{"case_id": "c1", "evaluator": "contains", "passed": False}])
    runner = CliRunner()

    ok = runner.invoke(app, ["compare", "--baseline", str(baseline), "--candidate", str(candidate), "--out", str(tmp_path / "ok.md"), "--max-pass-rate-drop", "0.2"])
    fail = runner.invoke(app, ["compare", "--baseline", str(baseline), "--candidate", str(candidate), "--out", str(tmp_path / "fail.md"), "--max-pass-rate-drop", "0.05", "--fail-on-new-failures"])

    assert ok.exit_code == 0, ok.output
    assert fail.exit_code == 1
    assert "Compare threshold failed" in fail.output
