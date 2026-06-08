from __future__ import annotations

from typing import Any


_RECOMMENDATION_LIBRARY = {
    "tool_output_missing_required_fact": {
        "priority": "P0",
        "type": "tool_fix",
        "title": "Inspect tool output for missing required facts",
        "actions": ["Compare baseline and candidate tool outputs", "Restore missing fields or update extraction logic", "Add affected cases to the active regression dataset"],
    },
    "prompt_instruction_gap": {
        "priority": "P1",
        "type": "prompt_change",
        "title": "Tighten prompt instructions for missing evaluator expectations",
        "actions": ["Add explicit instructions for the failed expectation", "Include a short positive example", "Rerun the affected capability subset"],
    },
    "policy_conflict": {
        "priority": "P0",
        "type": "policy_review",
        "title": "Review policy changes related to safety failures",
        "actions": ["Compare baseline and candidate policy versions", "Review new safety failures manually", "Rerun high-risk and safety-tagged cases"],
    },
    "safety_under_refusal": {
        "priority": "P0",
        "type": "policy_review",
        "title": "Fix safety under-refusal regressions",
        "actions": ["Audit unsafe outputs", "Strengthen refusal criteria", "Promote generated safety regressions"],
    },
    "safety_over_refusal": {
        "priority": "P1",
        "type": "policy_review",
        "title": "Review possible over-refusal behavior",
        "actions": ["Inspect safe prompts that were refused", "Clarify allowed-helpful behavior", "Rerun safety and helpfulness subsets"],
    },
    "max_tokens_truncation": {
        "priority": "P1",
        "type": "retry_with_repeats",
        "title": "Increase output budget or shorten prompt context",
        "actions": ["Inspect traces stopped by max_tokens", "Raise max_tokens or reduce context", "Rerun truncated cases"],
    },
    "latency_timeout": {
        "priority": "P1",
        "type": "retry_with_repeats",
        "title": "Investigate latency or timeout regressions",
        "actions": ["Check timeout settings", "Inspect slow tool calls", "Rerun with repeats to confirm stability"],
    },
    "model_behavior_change": {
        "priority": "P1",
        "type": "rollback",
        "title": "Review model behavior change before release",
        "actions": ["Compare model versions", "Rerun broad capability coverage", "Consider canary release if quality improves but risk remains"],
    },
    "flaky_behavior": {
        "priority": "P1",
        "type": "retry_with_repeats",
        "title": "Confirm flaky behavior with repeated runs",
        "actions": ["Increase repeats", "Separate flaky cases from true regressions", "Avoid promotion until high-risk flakes are resolved"],
    },
    "unknown": {
        "priority": "P2",
        "type": "evaluator_review",
        "title": "Review unexplained failures manually",
        "actions": ["Inspect failed traces", "Check evaluator expectations", "Add more specific metadata to cases"],
    },
}


def build_recommendations(diagnosis_report: dict[str, Any]) -> list[dict[str, Any]]:
    recommendations: list[dict[str, Any]] = []
    for item in diagnosis_report.get("diagnoses", []) or []:
        root_cause = str(item.get("root_cause") or "unknown")
        template = _RECOMMENDATION_LIBRARY.get(root_cause, _RECOMMENDATION_LIBRARY["unknown"])
        recommendations.append(
            {
                "priority": template["priority"],
                "type": template["type"],
                "title": template["title"],
                "reason": item.get("title") or root_cause,
                "actions": list(template["actions"]),
                "related_diagnoses": [item.get("id")],
            }
        )
    return recommendations


def recommendation_summaries_for(root_cause: str) -> list[str]:
    template = _RECOMMENDATION_LIBRARY.get(root_cause, _RECOMMENDATION_LIBRARY["unknown"])
    return list(template["actions"])
