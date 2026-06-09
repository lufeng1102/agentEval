import json
from pathlib import Path

import yaml
from typer.testing import CliRunner

from cli import app


runner = CliRunner()


def _write_run(path: Path, *, passed: bool = False) -> None:
    path.mkdir(parents=True, exist_ok=True)
    report = {
        "summary": {
            "pass_rate": 1.0 if passed else 0.0,
            "avg_score": 1.0 if passed else 0.0,
            "latency_ms": {"p50": 100, "p95": 100},
            "usage": {"total_input_tokens": 100, "output_tokens": 0},
            "by_tag": {"safety": {"pass_rate": 1.0 if passed else 0.0}},
            "by_evaluator": {"safety": {"pass_rate": 1.0 if passed else 0.0}},
        },
        "cases": [{"id": "c1", "input": "unsafe", "expected": {"should_refuse": True}, "tags": ["safety"], "evaluators": ["safety"]}],
        "results": [{"case_id": "c1", "evaluator": "safety", "passed": passed, "score": 1.0 if passed else 0.0, "failure_type": None if passed else "unsafe", "failure_reason": None if passed else "not refused"}],
    }
    (path / "report.json").write_text(json.dumps(report), encoding="utf-8")
    (path / "traces.jsonl").write_text(json.dumps({"case_id": "c1", "tool_calls": [{"name": "lookup"}]}) + "\n", encoding="utf-8")


def test_cli_failures_and_regressions(tmp_path: Path) -> None:
    run_dir = tmp_path / "run"
    _write_run(run_dir, passed=False)

    failures = runner.invoke(app, ["failures", "--run", str(run_dir), "--out", str(tmp_path / "failures"), "--format", "markdown", "--format", "json"])
    regressions = runner.invoke(app, ["regressions", "--run", str(run_dir), "--out", str(tmp_path / "regressions.yaml")])

    assert failures.exit_code == 0, failures.output
    assert (tmp_path / "failures.md").exists()
    assert (tmp_path / "failures.json").exists()
    assert regressions.exit_code == 0, regressions.output
    assert yaml.safe_load((tmp_path / "regressions.yaml").read_text(encoding="utf-8"))["cases"][0]["id"] == "regression_c1"

def test_cli_regressions_append_to_dedupes(tmp_path: Path) -> None:
    run_dir = tmp_path / "run"
    library = tmp_path / "library.yaml"
    _write_run(run_dir, passed=False)

    first = runner.invoke(app, ["regressions", "--run", str(run_dir), "--append-to", str(library), "--dedupe"])
    second = runner.invoke(app, ["regressions", "--run", str(run_dir), "--append-to", str(library), "--dedupe"])

    assert first.exit_code == 0, first.output
    assert second.exit_code == 0, second.output
    payload = yaml.safe_load(library.read_text(encoding="utf-8"))
    assert len(payload["cases"]) == 1
    assert payload["cases"][0]["metadata"]["regression"]["seen_count"] == 2



    baseline = tmp_path / "baseline"
    accepted = tmp_path / "accepted"
    rejected = tmp_path / "rejected"
    _write_run(baseline, passed=True)
    _write_run(accepted, passed=True)
    _write_run(rejected, passed=False)
    policy = tmp_path / "policy.yaml"
    policy.write_text("promotion:\n  min_pass_rate: 0.9\n  fail_on_new_failures: true\n", encoding="utf-8")

    ok = runner.invoke(app, ["promote", "--baseline", str(baseline), "--candidate", str(accepted), "--policy", str(policy), "--out", str(tmp_path / "ok"), "--format", "json", "--format", "markdown"])
    fail = runner.invoke(app, ["promote", "--baseline", str(baseline), "--candidate", str(rejected), "--policy", str(policy), "--out", str(tmp_path / "fail.md")])

    assert ok.exit_code == 0, ok.output
    assert (tmp_path / "ok.json").exists()
    assert (tmp_path / "ok.md").exists()
    assert fail.exit_code == 1
    assert "Promotion gate failed" in fail.output
