import os

import pytest

from evolution.judge import DiagnosisJudgeConfig, judge_diagnosis


@pytest.mark.anthropic_live
@pytest.mark.skipif(not os.environ.get("ANTHROPIC_API_KEY"), reason="ANTHROPIC_API_KEY is required for live Anthropic judge test")
def test_live_anthropic_diagnosis_judge_returns_schema() -> None:
    context = {
        "comparison": {
            "delta": {"pass_rate": -0.5, "avg_score": -0.5},
            "newly_failed": ["c1::contains"],
            "newly_passed": [],
            "agent_version_delta": {"toolset_version": {"baseline": "tools-v1", "candidate": "tools-v2"}},
        },
        "impact": {
            "summary": {"severity": "high", "newly_failed": 1, "pass_rate_delta": -0.5},
            "hotspots": [{"dimension": "capability", "key": "refund", "pass_rate_delta": -0.5, "severity": "high"}],
            "tool_impact": [{"tool": "policy_lookup", "candidate_uses": 1, "associated_failures": 1, "failure_rate_after_use": 1.0}],
        },
        "rule_diagnosis": {
            "summary": {"diagnoses": 1, "high_confidence": 1, "affected_cases": 1},
            "diagnoses": [
                {
                    "id": "diag_tool_output_missing_required_fact",
                    "title": "Tool output may be missing required facts",
                    "root_cause": "tool_output_missing_required_fact",
                    "confidence": 0.78,
                    "severity": "high",
                    "affected_cases": ["c1"],
                    "affected_evaluators": ["contains"],
                    "evidence": [{"type": "tool_trace", "description": "policy_lookup was used before missing required fact"}],
                    "recommendations": ["Inspect policy_lookup output fields"],
                }
            ],
        },
        "failure_clusters": [{"id": "missing_fact", "size": 1, "cases": ["c1"], "evaluators": ["contains"], "tool_names": ["policy_lookup"]}],
        "selected_cases": [{"id": "c1", "input": "What is the refund deadline?", "metadata": {"capability": "refund", "risk_level": "high"}}],
        "selected_results": [{"case_id": "c1", "evaluator": "contains", "passed": False, "failure_reason": "missing refund deadline"}],
        "selected_traces": [{"case_id": "c1", "tool_calls": [{"name": "policy_lookup", "arguments": {"topic": "refund"}}], "final_output": "You may be eligible for a refund."}],
    }
    config = DiagnosisJudgeConfig(
        cache={"enabled": False},
        cost={"max_output_tokens": 1200},
        input_limits={"max_context_json_chars": 20000},
    )

    report = pytest.importorskip("asyncio").run(judge_diagnosis(context, config))

    assert report["overall_assessment"]["release_risk"] in {"low", "medium", "high", "critical"}
    assert isinstance(report["overall_assessment"]["needs_human_review"], bool)
    assert isinstance(report["diagnoses"], list)
    assert report["diagnoses"]
    assert 0 <= report["diagnoses"][0]["confidence"] <= 1
    assert report["diagnoses"][0]["root_cause"]
