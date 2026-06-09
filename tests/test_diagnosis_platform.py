import json
from pathlib import Path

from evolution.diagnosis import diagnose_run_pair
from evolution.impact import analyze_impact
from evolution.recommendations import build_recommendations


def _write_run(path: Path, *, passed: bool, agent_version: dict | None = None, tool: str = "lookup", evaluator: str = "contains") -> None:
    path.mkdir(parents=True, exist_ok=True)
    report = {
        "summary": {
            "pass_rate": 1.0 if passed else 0.0,
            "avg_score": 1.0 if passed else 0.0,
            "latency_ms": {"p50": 100, "p95": 100},
            "usage": {"total_input_tokens": 10, "output_tokens": 5},
            "by_capability": {"refund": {"results": 1, "pass_rate": 1.0 if passed else 0.0, "avg_score": 1.0 if passed else 0.0}},
            "by_risk_level": {"high": {"results": 1, "pass_rate": 1.0 if passed else 0.0, "avg_score": 1.0 if passed else 0.0}},
            "by_evaluator": {evaluator: {"results": 1, "pass_rate": 1.0 if passed else 0.0, "avg_score": 1.0 if passed else 0.0}},
            "by_failure_type": {"missing_fact": {"results": 1, "pass_rate": 0.0, "avg_score": 0.0}} if not passed else {},
        },
        "cases": [{"id": "c1", "input": "q", "metadata": {"capability": "refund", "risk_level": "high"}, "tags": ["refund"]}],
        "results": [{"case_id": "c1", "evaluator": evaluator, "passed": passed, "score": 1.0 if passed else 0.0, "failure_type": None if passed else "missing_fact", "failure_reason": None if passed else "missing deadline"}],
    }
    (path / "report.json").write_text(json.dumps(report), encoding="utf-8")
    (path / "traces.jsonl").write_text(json.dumps({"case_id": "c1", "tool_calls": [{"name": tool}], "artifacts": {"dynamic": {"stop_reason": "end_turn"}}}) + "\n", encoding="utf-8")
    (path / "manifest.json").write_text(json.dumps({"agent_version": agent_version or {}}), encoding="utf-8")


def test_analyze_impact_reports_hotspots_and_tool_impact(tmp_path: Path) -> None:
    baseline = tmp_path / "baseline"
    candidate = tmp_path / "candidate"
    _write_run(baseline, passed=True, agent_version={"toolset_version": "t1"})
    _write_run(candidate, passed=False, agent_version={"toolset_version": "t2"})

    report = analyze_impact(baseline, candidate)

    assert report["summary"]["newly_failed"] == 1
    assert report["summary"]["severity"] in {"medium", "high", "critical"}
    assert report["hotspots"][0]["dimension"] in {"risk_level", "capability", "evaluator", "failure_type"}
    assert report["tool_impact"][0]["tool"] == "lookup"


def test_diagnose_run_pair_finds_tool_version_root_cause(tmp_path: Path) -> None:
    baseline = tmp_path / "baseline"
    candidate = tmp_path / "candidate"
    _write_run(baseline, passed=True, agent_version={"toolset_version": "t1"})
    _write_run(candidate, passed=False, agent_version={"toolset_version": "t2"})

    report = diagnose_run_pair(baseline, candidate)

    assert report["diagnoses"]
    assert report["diagnoses"][0]["root_cause"] == "tool_output_missing_required_fact"
    assert report["recommendations"][0]["type"] == "tool_fix"


def test_build_recommendations_has_actions() -> None:
    recommendations = build_recommendations({"diagnoses": [{"id": "d1", "root_cause": "prompt_instruction_gap", "title": "Prompt gap"}]})

    assert recommendations[0]["type"] == "prompt_change"
    assert recommendations[0]["actions"]
