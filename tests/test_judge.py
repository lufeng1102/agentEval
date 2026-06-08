import json
from pathlib import Path

from evolution.impact import analyze_impact
from evolution.diagnosis import diagnose_run_pair
from evolution.judge import (
    DiagnosisJudgeConfig,
    build_judge_context,
    judge_diagnosis,
    load_judge_config,
    merge_judge_diagnosis,
    sanitize_for_judge,
    should_run_judge,
)


class FakeJudge:
    async def judge(self, context, config):
        return {
            "overall_assessment": {"summary": "Judge confirms regression.", "release_risk": "high", "needs_human_review": True},
            "diagnoses": [
                {
                    "matches_rule_diagnosis_id": context["rule_diagnosis"]["diagnoses"][0]["id"],
                    "verdict": "supported",
                    "title": "Confirmed tool issue",
                    "root_cause": "tool_output_missing_required_fact",
                    "confidence": 0.9,
                    "severity": "high",
                    "affected_cases": ["c1"],
                    "affected_evaluators": ["contains"],
                    "likely_components": ["toolset"],
                    "reasoning_summary": "The same tool appears in the failed trace.",
                    "evidence": [{"type": "trace_pattern", "description": "lookup used before failure"}],
                    "alternative_root_causes": [],
                    "recommended_actions": ["Inspect lookup output"],
                    "human_review_questions": ["Was deadline present?"],
                }
            ],
        }


def _write_run(path: Path, *, passed: bool) -> None:
    path.mkdir(parents=True, exist_ok=True)
    report = {
        "summary": {"pass_rate": 1.0 if passed else 0.0, "avg_score": 1.0 if passed else 0.0, "latency_ms": {"p50": 1, "p95": 1}, "usage": {"total_input_tokens": 1, "output_tokens": 1}, "by_risk_level": {"high": {"results": 1, "pass_rate": 1.0 if passed else 0.0, "avg_score": 1.0 if passed else 0.0}}, "by_evaluator": {"contains": {"results": 1, "pass_rate": 1.0 if passed else 0.0, "avg_score": 1.0 if passed else 0.0}}},
        "cases": [{"id": "c1", "input": "q", "metadata": {"risk_level": "high", "authorization": "Bearer secret"}}],
        "results": [{"case_id": "c1", "evaluator": "contains", "passed": passed, "score": 1.0 if passed else 0.0, "failure_type": None if passed else "missing_fact", "failure_reason": None if passed else "missing deadline"}],
    }
    (path / "report.json").write_text(json.dumps(report), encoding="utf-8")
    (path / "traces.jsonl").write_text(json.dumps({"case_id": "c1", "tool_calls": [{"name": "lookup", "output": "x" * 100}], "authorization": "Bearer abc"}) + "\n", encoding="utf-8")
    (path / "manifest.json").write_text(json.dumps({"agent_version": {"toolset_version": "t2" if not passed else "t1"}}), encoding="utf-8")


def test_judge_config_sanitize_trigger_context_and_merge(tmp_path: Path, monkeypatch) -> None:
    baseline = tmp_path / "baseline"
    candidate = tmp_path / "candidate"
    _write_run(baseline, passed=True)
    _write_run(candidate, passed=False)
    config = DiagnosisJudgeConfig()
    rule = diagnose_run_pair(baseline, candidate)
    impact = analyze_impact(baseline, candidate)

    assert should_run_judge(rule, impact, config, "never")[0] is False
    assert should_run_judge(rule, impact, config, "always")[0] is True
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test")
    assert should_run_judge(rule, impact, config, "auto")[0] is True

    sanitized = sanitize_for_judge({"authorization": "Bearer abc", "nested": {"token": "secret"}, "text": "x" * 20000}, config)
    assert sanitized["authorization"] == "[REDACTED]"
    assert sanitized["nested"]["token"] == "[REDACTED]"
    assert "[truncated]" in sanitized["text"]

    context = build_judge_context(baseline, candidate, rule, impact, config)
    assert context["selected_cases"]
    assert context["selected_traces"][0]["authorization"] == "[REDACTED]"

    judge_report = __import__("asyncio").run(judge_diagnosis(context, config, FakeJudge()))
    merged = merge_judge_diagnosis(rule, judge_report)
    assert merged["judge"]["used"] is True
    assert merged["summary"]["needs_human_review"] is True
    assert merged["diagnoses"][0]["judge"]["verdict"] == "supported"
    assert merged["diagnoses"][0]["confidence"] == 0.9


def test_load_judge_config_from_yaml(tmp_path: Path) -> None:
    path = tmp_path / "judge.yaml"
    path.write_text("diagnosis_judge:\n  model: claude-opus-4-8\n  input_limits:\n    max_clusters: 2\n", encoding="utf-8")
    config = load_judge_config(path)
    assert config.model == "claude-opus-4-8"
    assert config.input_limits.max_clusters == 2
