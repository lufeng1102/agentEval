from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from compare import compare_runs
from evolution.artifacts import load_run_artifacts
from evolution.failures import cluster_failures
from evolution.impact import analyze_impact
from evolution.recommendations import build_recommendations, recommendation_summaries_for


ROOT_CAUSE_UNKNOWN = "unknown"


def diagnose_run_pair(baseline: str | Path, candidate: str | Path) -> dict[str, Any]:
    comparison = compare_runs(baseline, candidate)
    candidate_artifacts = load_run_artifacts(candidate)
    clusters = cluster_failures(candidate_artifacts.report, candidate_artifacts.traces)
    impact = analyze_impact(baseline, candidate)
    version_delta = comparison.get("agent_version_delta", {}) or {}
    diagnoses: list[dict[str, Any]] = []
    case_metadata = _case_metadata(candidate_artifacts.report)

    for cluster in clusters.get("clusters", []) or []:
        root_cause, confidence, components, evidence = _classify_cluster(cluster, candidate_artifacts.traces, version_delta)
        severity = _cluster_severity(cluster, case_metadata, root_cause)
        diagnoses.append(
            {
                "id": _diagnosis_id(root_cause, cluster.get("id", "cluster")),
                "title": _title_for(root_cause, cluster),
                "root_cause": root_cause,
                "confidence": confidence,
                "severity": severity,
                "affected_cases": cluster.get("cases", []),
                "affected_evaluators": cluster.get("evaluators", []),
                "affected_capabilities": sorted({case_metadata.get(case, {}).get("capability") for case in cluster.get("cases", []) if case_metadata.get(case, {}).get("capability")}),
                "affected_risk_levels": sorted({case_metadata.get(case, {}).get("risk_level") for case in cluster.get("cases", []) if case_metadata.get(case, {}).get("risk_level")}),
                "evidence": evidence,
                "likely_components": components,
                "recommendations": recommendation_summaries_for(root_cause),
            }
        )

    if not diagnoses and comparison.get("newly_failed"):
        diagnoses.append(
            {
                "id": "diag_unknown_regression",
                "title": "Candidate introduced failures without a matching diagnosis rule",
                "root_cause": ROOT_CAUSE_UNKNOWN,
                "confidence": 0.25,
                "severity": impact.get("summary", {}).get("severity", "medium"),
                "affected_cases": sorted({item.split("::", 1)[0] for item in comparison.get("newly_failed", [])}),
                "affected_evaluators": sorted({item.split("::", 1)[1] for item in comparison.get("newly_failed", []) if "::" in item}),
                "affected_capabilities": [],
                "affected_risk_levels": [],
                "evidence": [{"type": "newly_failed", "description": f"{len(comparison.get('newly_failed', []))} newly failed evaluator results"}],
                "likely_components": [],
                "recommendations": recommendation_summaries_for(ROOT_CAUSE_UNKNOWN),
            }
        )

    diagnoses.sort(key=lambda item: (-_severity_rank(item["severity"]), -float(item["confidence"]), item["id"]))
    report = {
        "baseline": str(baseline),
        "candidate": str(candidate),
        "summary": {
            "diagnoses": len(diagnoses),
            "high_confidence": sum(1 for item in diagnoses if float(item.get("confidence", 0)) >= 0.75),
            "affected_cases": len({case for item in diagnoses for case in item.get("affected_cases", [])}),
            "top_root_causes": list(dict.fromkeys(item["root_cause"] for item in diagnoses[:5])),
        },
        "impact_summary": impact.get("summary", {}),
        "diagnoses": diagnoses,
    }
    report["recommendations"] = build_recommendations(report)
    return report


def write_diagnosis_json(path: str | Path, report: dict[str, Any]) -> None:
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")


def write_diagnosis_markdown(path: str | Path, report: dict[str, Any]) -> None:
    summary = report.get("summary", {})
    lines = [
        "# AgentEval Diagnosis Report",
        "",
        f"- Baseline: `{report.get('baseline')}`",
        f"- Candidate: `{report.get('candidate')}`",
        f"- Diagnoses: {summary.get('diagnoses', 0)}",
        f"- High confidence: {summary.get('high_confidence', 0)}",
        f"- Affected cases: {summary.get('affected_cases', 0)}",
        "",
    ]
    if report.get("judge"):
        judge = report.get("judge", {})
        assessment = judge.get("overall_assessment", {}) or {}
        lines.extend([
            "## LLM Judge",
            "",
            f"- Used: {judge.get('used', False)}",
            f"- Model: `{judge.get('model')}`",
            f"- Cached: {judge.get('cached', False)}",
            f"- Overall release risk: {assessment.get('release_risk', 'unknown')}",
            f"- Needs human review: {assessment.get('needs_human_review', False)}",
            "",
            assessment.get("summary", ""),
            "",
        ])
    for item in report.get("diagnoses", []) or []:
        lines.extend([
            f"## {item.get('title')}",
            "",
            f"- Root cause: `{item.get('root_cause')}`",
            f"- Confidence: {float(item.get('confidence', 0)):.2f}",
            f"- Severity: **{item.get('severity')}**",
            f"- Cases: {', '.join(item.get('affected_cases', [])) or 'None'}",
            f"- Evaluators: {', '.join(item.get('affected_evaluators', [])) or 'None'}",
            f"- Likely components: {', '.join(item.get('likely_components', [])) or 'None'}",
            "",
            "### Evidence",
            "",
        ])
        lines.extend([f"- {evidence.get('description')}" for evidence in item.get("evidence", [])] or ["None"])
        lines.extend(["", "### Recommendations", ""])
        lines.extend([f"- {rec}" for rec in item.get("recommendations", [])] or ["None"])
        if item.get("judge"):
            judge = item.get("judge", {})
            lines.extend(["", "### Judge Verdict", ""])
            lines.append(f"- Verdict: {judge.get('verdict')}")
            if judge.get("confidence") is not None:
                lines.append(f"- Judge confidence: {float(judge.get('confidence', 0)):.2f}")
            if judge.get("reasoning_summary"):
                lines.append(f"- Reasoning: {judge.get('reasoning_summary')}")
            if judge.get("human_review_questions"):
                lines.append("- Human review questions:")
                lines.extend([f"  - {question}" for question in judge.get("human_review_questions", [])])
        lines.append("")
    lines.extend(["## Action Recommendations", ""])
    for rec in report.get("recommendations", []) or []:
        lines.append(f"- **{rec.get('priority')} {rec.get('type')}**: {rec.get('title')} — {rec.get('reason')}")
    if not report.get("recommendations"):
        lines.append("None")
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _classify_cluster(cluster: dict[str, Any], traces: list[dict[str, Any]], version_delta: dict[str, Any]) -> tuple[str, float, list[str], list[dict[str, str]]]:
    evaluators = set(cluster.get("evaluators", []) or [])
    failure_types = {str(item) for item in cluster.get("failure_types", []) or []}
    stop_reasons = set(cluster.get("stop_reasons", []) or [])
    tool_names = cluster.get("tool_names", []) or []
    evidence: list[dict[str, str]] = [{"type": "failure_cluster", "description": f"Cluster {cluster.get('id')} contains {cluster.get('size', 0)} failures"}]
    if version_delta:
        evidence.append({"type": "version_delta", "description": f"Agent version changed: {', '.join(version_delta.keys())}"})
    if tool_names:
        evidence.append({"type": "tool_trace", "description": f"Affected traces used tools: {', '.join(tool_names)}"})
    if "max_tokens" in stop_reasons:
        return "max_tokens_truncation", 0.9, ["runner", "prompt"], evidence + [{"type": "stop_reason", "description": "Candidate traces stopped because max_tokens was reached"}]
    if "timeout" in stop_reasons:
        return "latency_timeout", 0.9, ["runner", "toolset"], evidence + [{"type": "stop_reason", "description": "Candidate traces stopped because of timeout"}]
    if "safety" in evaluators:
        if "policy_version" in version_delta:
            return "policy_conflict", 0.82, ["policy"], evidence
        return "safety_under_refusal", 0.7, ["policy", "prompt"], evidence
    if "toolset_version" in version_delta and tool_names and ("contains" in evaluators or any("missing" in item for item in failure_types)):
        return "tool_output_missing_required_fact", 0.78, ["toolset"], evidence
    if ("prompt_version" in version_delta or "prompt_hash" in version_delta) and ({"contains", "exact_match"} & evaluators):
        return "prompt_instruction_gap", 0.72, ["prompt"], evidence
    if "model" in version_delta:
        return "model_behavior_change", 0.65, ["model"], evidence
    return ROOT_CAUSE_UNKNOWN, 0.3, [], evidence


def _case_metadata(report: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {str(case.get("id")): case.get("metadata", {}) or {} for case in report.get("cases", []) or [] if isinstance(case, dict)}


def _cluster_severity(cluster: dict[str, Any], case_metadata: dict[str, dict[str, Any]], root_cause: str) -> str:
    risk_levels = {case_metadata.get(case, {}).get("risk_level") for case in cluster.get("cases", [])}
    if root_cause in {"policy_conflict", "safety_under_refusal"} or "critical" in risk_levels:
        return "critical"
    if "high" in risk_levels or int(cluster.get("size", 0)) >= 5:
        return "high"
    if int(cluster.get("size", 0)) >= 2:
        return "medium"
    return "low"


def _title_for(root_cause: str, cluster: dict[str, Any]) -> str:
    labels = {
        "tool_output_missing_required_fact": "Tool output may be missing required facts",
        "prompt_instruction_gap": "Prompt instructions may not cover failed expectations",
        "policy_conflict": "Policy change may have introduced safety regressions",
        "safety_under_refusal": "Safety evaluator failures need review",
        "max_tokens_truncation": "Responses may be truncated by max token limits",
        "latency_timeout": "Runs may be failing due to timeout",
        "model_behavior_change": "Model change may have shifted behavior",
        "unknown": "Unclassified failure cluster requires review",
    }
    return f"{labels.get(root_cause, labels['unknown'])}: {cluster.get('id')}"


def _diagnosis_id(root_cause: str, cluster_id: str) -> str:
    safe = "".join(ch if ch.isalnum() else "_" for ch in f"{root_cause}_{cluster_id}".lower()).strip("_")
    return f"diag_{safe[:80]}"


def _severity_rank(severity: str) -> int:
    return {"low": 1, "medium": 2, "high": 3, "critical": 4}.get(severity, 0)
