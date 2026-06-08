import json
from pathlib import Path

from typer.testing import CliRunner

from cli import app


runner = CliRunner()


def _write_run(path: Path, *, passed: bool) -> None:
    path.mkdir(parents=True, exist_ok=True)
    report = {
        "summary": {"pass_rate": 1.0 if passed else 0.0, "avg_score": 1.0 if passed else 0.0, "latency_ms": {"p50": 1, "p95": 1}, "usage": {"total_input_tokens": 1, "output_tokens": 1}, "by_risk_level": {"high": {"results": 1, "pass_rate": 1.0 if passed else 0.0, "avg_score": 1.0 if passed else 0.0}}, "by_evaluator": {"contains": {"results": 1, "pass_rate": 1.0 if passed else 0.0, "avg_score": 1.0 if passed else 0.0}}},
        "cases": [{"id": "c1", "input": "q", "metadata": {"risk_level": "high"}}],
        "results": [{"case_id": "c1", "evaluator": "contains", "passed": passed, "score": 1.0 if passed else 0.0, "failure_type": None if passed else "missing_fact", "failure_reason": None if passed else "missing"}],
    }
    (path / "report.json").write_text(json.dumps(report), encoding="utf-8")
    (path / "traces.jsonl").write_text(json.dumps({"case_id": "c1", "tool_calls": [{"name": "lookup"}]}) + "\n", encoding="utf-8")
    (path / "manifest.json").write_text(json.dumps({"agent_version": {"toolset_version": "t2" if not passed else "t1"}}), encoding="utf-8")


def test_diagnose_judge_never_records_skipped_metadata(tmp_path: Path) -> None:
    baseline = tmp_path / "baseline"
    candidate = tmp_path / "candidate"
    _write_run(baseline, passed=True)
    _write_run(candidate, passed=False)

    result = runner.invoke(app, ["diagnose", "--baseline", str(baseline), "--candidate", str(candidate), "--out", str(tmp_path / "diagnosis"), "--format", "json", "--judge", "never"])

    assert result.exit_code == 0, result.output
    payload = json.loads((tmp_path / "diagnosis").read_text(encoding="utf-8"))
    assert payload["judge"]["used"] is False
    assert payload["judge"]["skipped_reason"] == "judge mode is never"


def test_diagnose_judge_strict_fails_without_api_key(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    baseline = tmp_path / "baseline"
    candidate = tmp_path / "candidate"
    _write_run(baseline, passed=True)
    _write_run(candidate, passed=False)

    result = runner.invoke(app, ["diagnose", "--baseline", str(baseline), "--candidate", str(candidate), "--out", str(tmp_path / "diagnosis.json"), "--judge", "always", "--judge-strict"])

    assert result.exit_code != 0
