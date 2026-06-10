import json
from pathlib import Path

from typer.testing import CliRunner

from cli import app

runner = CliRunner()


def _write_run(path: Path, *, passed: bool, score: float = 1.0) -> None:
    path.mkdir(parents=True, exist_ok=True)
    report = {
        "summary": {"pass_rate": 1.0 if passed else 0.0, "avg_score": score, "latency_ms": {"p50": 100, "p95": 100}, "usage": {"total_input_tokens": 1, "output_tokens": 1}},
        "cases": [{"id": "c1", "input": "q", "tags": ["support"], "metadata": {"capability": "refund", "risk_level": "low"}}],
        "runs": [{"case_id": "c1", "final_output": "ok" if passed else "bad", "latency_ms": 100, "errors": []}],
        "results": [{"case_id": "c1", "evaluator": "contains", "passed": passed, "score": score}],
    }
    (path / "report.json").write_text(json.dumps(report), encoding="utf-8")
    (path / "traces.jsonl").write_text(json.dumps({"case_id": "c1", "final_output": "ok" if passed else "bad", "latency_ms": 100, "errors": [], "tool_calls": []}) + "\n", encoding="utf-8")
    (path / "manifest.json").write_text("{}", encoding="utf-8")


def test_pairwise_cli_writes_json_and_markdown(tmp_path: Path) -> None:
    baseline = tmp_path / "baseline"
    candidate = tmp_path / "candidate"
    _write_run(baseline, passed=False, score=0.2)
    _write_run(candidate, passed=True, score=1.0)

    result = runner.invoke(app, ["pairwise", "--baseline", str(baseline), "--candidate", str(candidate), "--out", str(tmp_path / "pairwise"), "--format", "json", "--format", "markdown", "--judge", "never"])

    assert result.exit_code == 0, result.output
    assert (tmp_path / "pairwise.json").exists()
    assert (tmp_path / "pairwise.md").exists()
    assert json.loads((tmp_path / "pairwise.json").read_text(encoding="utf-8"))["summary"]["candidate_wins"] == 1


def test_pairwise_cli_threshold_failure(tmp_path: Path) -> None:
    baseline = tmp_path / "baseline"
    candidate = tmp_path / "candidate"
    _write_run(baseline, passed=True, score=1.0)
    _write_run(candidate, passed=False, score=0.2)

    result = runner.invoke(app, ["pairwise", "--baseline", str(baseline), "--candidate", str(candidate), "--out", str(tmp_path / "pairwise.md"), "--fail-under-candidate-win-rate", "0.5"])

    assert result.exit_code == 1
    assert "Pairwise threshold failed" in result.output


def test_pairwise_cli_judge_always_non_strict_falls_back_without_api_key(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    baseline = tmp_path / "baseline"
    candidate = tmp_path / "candidate"
    _write_run(baseline, passed=True, score=1.0)
    _write_run(candidate, passed=True, score=1.0)

    result = runner.invoke(app, ["pairwise", "--baseline", str(baseline), "--candidate", str(candidate), "--out", str(tmp_path / "pairwise.json"), "--format", "json", "--judge", "always"])

    assert result.exit_code == 0, result.output
    payload = json.loads((tmp_path / "pairwise.json").read_text(encoding="utf-8"))
    assert payload["summary"]["judge_skipped_reason"] == "ANTHROPIC_API_KEY is not set"
    assert payload["summary"]["ties"] == 1
