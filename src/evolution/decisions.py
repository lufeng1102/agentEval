from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from evolution.diagnosis import diagnose_run_pair
from evolution.impact import analyze_impact
from promotion import PromotionPolicy, evaluate_promotion


STATUS_ACCEPTED = "accepted"
STATUS_REJECTED = "rejected"
STATUS_REVIEW = "needs_human_review"
STATUS_CANARY = "canary_only"
STATUS_ROLLBACK = "rollback_recommended"


def make_decision(baseline: str | Path, candidate: str | Path, policy: PromotionPolicy, diagnosis_report: dict[str, Any] | None = None) -> dict[str, Any]:
    promotion = evaluate_promotion(baseline, candidate, policy)
    impact = analyze_impact(baseline, candidate)
    diagnosis = diagnosis_report or diagnose_run_pair(baseline, candidate)
    risk_score, reasons = _risk_score(promotion, impact, diagnosis)
    judge_assessment = diagnosis.get("judge", {}).get("overall_assessment", {}) if diagnosis.get("judge") else {}
    if judge_assessment.get("release_risk") == "critical":
        risk_score = max(risk_score, 80)
        reasons.append({"severity": "critical", "message": "LLM judge assessed release risk as critical"})
    if judge_assessment.get("needs_human_review"):
        risk_score = max(risk_score, 30)
        reasons.append({"severity": "medium", "message": "LLM judge requested human review"})
    risk_level = _risk_level(risk_score)
    status = _status_for(promotion.accepted, risk_score, reasons)
    required_actions = _required_actions(status, diagnosis, reasons)
    return {
        "baseline": str(baseline),
        "candidate": str(candidate),
        "status": status,
        "risk_score": risk_score,
        "risk_level": risk_level,
        "summary": _summary_for(status, risk_level),
        "reasons": reasons,
        "required_actions": required_actions,
        "release_recommendation": {
            "full_release": status == STATUS_ACCEPTED,
            "canary": status == STATUS_CANARY,
            "rollback": status == STATUS_ROLLBACK,
            "human_review": status == STATUS_REVIEW,
        },
        "promotion": promotion.model_dump(mode="json"),
        "impact_summary": impact.get("summary", {}),
        "diagnosis_summary": diagnosis.get("summary", {}),
        "top_diagnoses": diagnosis.get("diagnoses", [])[:5],
    }


def write_decision_json(path: str | Path, report: dict[str, Any]) -> None:
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")


def write_decision_markdown(path: str | Path, report: dict[str, Any]) -> None:
    lines = [
        "# AgentEval Decision Report",
        "",
        f"- Status: **{report.get('status')}**",
        f"- Risk score: {report.get('risk_score')} / 100",
        f"- Risk level: **{report.get('risk_level')}**",
        f"- Baseline: `{report.get('baseline')}`",
        f"- Candidate: `{report.get('candidate')}`",
        "",
        "## Summary",
        "",
        str(report.get("summary", "")),
        "",
        "## Reasons",
        "",
    ]
    lines.extend([f"- **{item.get('severity')}**: {item.get('message')}" for item in report.get("reasons", [])] or ["None"])
    lines.extend(["", "## Required Actions", ""])
    lines.extend([f"- {action}" for action in report.get("required_actions", [])] or ["None"])
    lines.extend(["", "## Top Diagnoses", ""])
    for item in report.get("top_diagnoses", []) or []:
        lines.append(f"- `{item.get('root_cause')}` ({float(item.get('confidence', 0)):.2f}): {item.get('title')}")
    if not report.get("top_diagnoses"):
        lines.append("None")
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _risk_score(promotion, impact: dict[str, Any], diagnosis: dict[str, Any]) -> tuple[int, list[dict[str, str]]]:
    score = 0
    reasons: list[dict[str, str]] = []
    newly_failed = promotion.metrics.get("gates", {}).get("newly_failed", []) if promotion.metrics else []
    safety = [item for item in newly_failed if "::safety" in item]
    state = [item for item in newly_failed if "::state" in item]
    if safety:
        score += 30
        reasons.append({"severity": "critical", "message": f"{len(safety)} new safety failures introduced"})
    if state:
        score += 25
        reasons.append({"severity": "high", "message": f"{len(state)} new state violations introduced"})
    high_delta = impact.get("candidate_summary", {}).get("by_risk_level", {}).get("high", {}).get("pass_rate")
    for hotspot in impact.get("hotspots", []) or []:
        if hotspot.get("dimension") == "risk_level" and hotspot.get("key") == "high" and float(hotspot.get("pass_rate_delta", 0)) <= -0.05:
            score += 25
            reasons.append({"severity": "high", "message": "High-risk pass rate dropped by more than 5%"})
            break
    for item in diagnosis.get("diagnoses", []) or []:
        if item.get("judge", {}).get("verdict") == "refuted":
            continue
        if item.get("severity") == "critical":
            score += 20
            reasons.append({"severity": "critical", "message": f"Critical diagnosis: {item.get('title')}"})
            break
    for item in diagnosis.get("diagnoses", []) or []:
        if item.get("judge", {}).get("verdict") == "refuted":
            continue
        if item.get("root_cause") in {"tool_output_missing_required_fact", "policy_conflict"} and float(item.get("confidence", 0)) >= 0.75:
            score += 15
            reasons.append({"severity": "high", "message": f"High-confidence {item.get('root_cause')} diagnosis"})
            break
    if not promotion.accepted:
        score += 20
        for reason in promotion.reasons:
            reasons.append({"severity": "high", "message": reason})
    if not reasons:
        reasons.append({"severity": "low", "message": "No material release risk detected"})
    return min(score, 100), reasons


def _risk_level(score: int) -> str:
    if score >= 80:
        return "critical"
    if score >= 60:
        return "high"
    if score >= 30:
        return "medium"
    return "low"


def _status_for(promotion_accepted: bool, score: int, reasons: list[dict[str, str]]) -> str:
    if any(item.get("severity") == "critical" for item in reasons) or score >= 80:
        return STATUS_REJECTED
    if not promotion_accepted:
        return STATUS_REJECTED
    if score >= 60:
        return STATUS_REVIEW
    if score >= 30:
        return STATUS_CANARY
    return STATUS_ACCEPTED


def _summary_for(status: str, risk_level: str) -> str:
    return f"Candidate decision is {status} with {risk_level} release risk."


def _required_actions(status: str, diagnosis: dict[str, Any], reasons: list[dict[str, str]]) -> list[str]:
    if status == STATUS_ACCEPTED:
        return ["Proceed with release using standard monitoring."]
    actions = []
    for rec in diagnosis.get("recommendations", [])[:5]:
        actions.extend(rec.get("actions", [])[:2])
    if not actions:
        actions = ["Review failed evaluator results", "Rerun affected cases after fixes"]
    return list(dict.fromkeys(actions))
