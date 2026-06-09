import json
from pathlib import Path

from evolution.decisions import make_decision
from evolution.flaky import analyze_flaky
from evolution.leaderboard import build_leaderboard
from evolution.pr_summary import build_pr_summary
from evolution.regression_status import mark_regression, summarize_regressions, update_regression_status
from promotion import PromotionPolicy


def _write_report_run(path: Path, *, passed: bool, results: list[dict] | None = None) -> None:
    path.mkdir(parents=True, exist_ok=True)
    report = {
        "summary": {
            "pass_rate": 1.0 if passed else 0.0,
            "avg_score": 1.0 if passed else 0.0,
            "latency_ms": {"p50": 1, "p95": 1},
            "usage": {"total_input_tokens": 1, "output_tokens": 1},
            "by_risk_level": {"high": {"results": 1, "pass_rate": 1.0 if passed else 0.0, "avg_score": 1.0 if passed else 0.0}},
        },
        "cases": [{"id": "c1", "input": "q", "metadata": {"risk_level": "high", "capability": "refund"}}],
        "results": results if results is not None else [{"case_id": "c1", "evaluator": "safety", "passed": passed, "score": 1.0 if passed else 0.0, "failure_type": None if passed else "unsafe", "failure_reason": None if passed else "not refused"}],
    }
    (path / "report.json").write_text(json.dumps(report), encoding="utf-8")
    (path / "traces.jsonl").write_text(json.dumps({"case_id": "c1", "tool_calls": []}) + "\n", encoding="utf-8")
    (path / "manifest.json").write_text(json.dumps({"agent_version": {"policy_version": "p2" if not passed else "p1"}}), encoding="utf-8")


def test_make_decision_rejects_safety_regression(tmp_path: Path) -> None:
    baseline = tmp_path / "baseline"
    candidate = tmp_path / "candidate"
    _write_report_run(baseline, passed=True)
    _write_report_run(candidate, passed=False)

    report = make_decision(baseline, candidate, PromotionPolicy(min_pass_rate=1.0, fail_on_new_failures=True, fail_on_new_safety_failures=True))

    assert report["status"] == "rejected"
    assert report["risk_score"] >= 30
    assert report["required_actions"]


def test_analyze_flaky_detects_mixed_repeats(tmp_path: Path) -> None:
    run = tmp_path / "run"
    results = [
        {"case_id": "c1", "evaluator": "contains", "passed": True, "score": 1},
        {"case_id": "c1", "evaluator": "contains", "passed": False, "score": 0},
        {"case_id": "c1", "evaluator": "contains", "passed": True, "score": 1},
    ]
    _write_report_run(run, passed=True, results=results)

    report = analyze_flaky(run)

    assert report["summary"]["flaky_pairs"] == 1
    assert report["flaky_results"][0]["pass_rate"] == 2 / 3


def test_regression_status_lifecycle(tmp_path: Path) -> None:
    dataset = tmp_path / "regressions.yaml"
    dataset.write_text(
        """
metadata: {}
cases:
  - id: regression_c1
    input: q
    metadata:
      regression:
        status: active
        severity: high
""".strip(),
        encoding="utf-8",
    )
    run = tmp_path / "run"
    _write_report_run(run, passed=True, results=[{"case_id": "regression_c1", "evaluator": "contains", "passed": True, "score": 1}])

    assert summarize_regressions(dataset)["by_status"]["active"] == 1
    assert update_regression_status(dataset, run)["by_status"]["fixed"] == 1
    assert mark_regression(dataset, "regression_c1", "ignored", "ambiguous")["status"] == "ignored"


def test_leaderboard_and_pr_summary(tmp_path: Path) -> None:
    leaderboard = build_leaderboard("baseline", [{"id": "c1", "run_dir": "runs/c1", "summary": {"pass_rate": 1.0, "avg_score": 0.9, "usage": {"total_input_tokens": 1, "output_tokens": 1}, "latency_ms": {"p95": 10}}, "decision": {"status": "accepted", "risk_score": 10}}])
    assert leaderboard["best"]["overall"] == "c1"

    decision = tmp_path / "decision.json"
    decision.write_text(json.dumps({"status": "accepted", "risk_score": 10, "risk_level": "low", "reasons": [{"message": "ok"}], "required_actions": ["ship"]}), encoding="utf-8")
    summary = build_pr_summary(decision)
    assert "AgentEval Decision: accepted" in summary
