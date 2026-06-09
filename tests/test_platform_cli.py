import json
from pathlib import Path

from typer.testing import CliRunner

from cli import app


runner = CliRunner()


def _write_run(path: Path, *, passed: bool) -> None:
    path.mkdir(parents=True, exist_ok=True)
    report = {
        "summary": {
            "pass_rate": 1.0 if passed else 0.0,
            "avg_score": 1.0 if passed else 0.0,
            "latency_ms": {"p50": 1, "p95": 1},
            "usage": {"total_input_tokens": 1, "output_tokens": 1},
            "by_capability": {"refund": {"results": 1, "pass_rate": 1.0 if passed else 0.0, "avg_score": 1.0 if passed else 0.0}},
            "by_risk_level": {"high": {"results": 1, "pass_rate": 1.0 if passed else 0.0, "avg_score": 1.0 if passed else 0.0}},
            "by_evaluator": {"contains": {"results": 1, "pass_rate": 1.0 if passed else 0.0, "avg_score": 1.0 if passed else 0.0}},
        },
        "cases": [{"id": "c1", "input": "q", "metadata": {"capability": "refund", "risk_level": "high"}}],
        "results": [{"case_id": "c1", "evaluator": "contains", "passed": passed, "score": 1.0 if passed else 0.0, "failure_type": None if passed else "missing_fact", "failure_reason": None if passed else "missing"}],
    }
    (path / "report.json").write_text(json.dumps(report), encoding="utf-8")
    (path / "traces.jsonl").write_text(json.dumps({"case_id": "c1", "tool_calls": [{"name": "lookup"}]}) + "\n", encoding="utf-8")
    (path / "manifest.json").write_text(json.dumps({"agent_version": {"toolset_version": "t2" if not passed else "t1"}}), encoding="utf-8")


def test_impact_diagnose_decide_flaky_and_pr_summary_cli(tmp_path: Path) -> None:
    baseline = tmp_path / "baseline"
    candidate = tmp_path / "candidate"
    _write_run(baseline, passed=True)
    _write_run(candidate, passed=False)
    policy = tmp_path / "policy.yaml"
    policy.write_text("promotion:\n  min_pass_rate: 1.0\n  fail_on_new_failures: true\n", encoding="utf-8")

    impact = runner.invoke(app, ["impact", "--baseline", str(baseline), "--candidate", str(candidate), "--out", str(tmp_path / "impact"), "--format", "markdown", "--format", "json"])
    diagnosis = runner.invoke(app, ["diagnose", "--baseline", str(baseline), "--candidate", str(candidate), "--out", str(tmp_path / "diagnosis"), "--format", "markdown", "--format", "json"])
    decision = runner.invoke(app, ["decide", "--baseline", str(baseline), "--candidate", str(candidate), "--policy", str(policy), "--out", str(tmp_path / "decision"), "--format", "markdown", "--format", "json"])
    flaky = runner.invoke(app, ["flaky", "--run", str(candidate), "--out", str(tmp_path / "flaky"), "--format", "json"])
    summary = runner.invoke(app, ["pr-summary", "--decision", str(tmp_path / "decision.json"), "--diagnosis", str(tmp_path / "diagnosis.json"), "--compare", str(tmp_path / "impact.json"), "--out", str(tmp_path / "pr.md")])

    assert impact.exit_code == 0, impact.output
    assert diagnosis.exit_code == 0, diagnosis.output
    assert decision.exit_code == 1
    assert flaky.exit_code == 0, flaky.output
    assert summary.exit_code == 0, summary.output
    assert (tmp_path / "impact.json").exists()
    assert (tmp_path / "diagnosis.md").exists()
    assert (tmp_path / "decision.json").exists()
    assert "AgentEval Decision" in (tmp_path / "pr.md").read_text(encoding="utf-8")
