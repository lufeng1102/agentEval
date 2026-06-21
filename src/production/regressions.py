from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from evolution.regressions import append_regression_dataset, write_regression_dataset
from production.feedback import join_feedback, load_user_feedback
from production.ingest import load_production_events
from production.report import write_report_json, write_report_text
from production.summary import is_negative_feedback
from review.golden import load_golden_labels
from review.labels import load_human_labels


def production_feedback_to_regressions(
    events_path: str | Path,
    feedback_path: str | Path,
    *,
    only_negative: bool = True,
    limit: int | None = None,
    category: str | None = None,
    review_labels_path: str | Path | None = None,
    require_reviewed: bool = False,
    golden_only: bool = False,
) -> dict[str, Any]:
    events = load_production_events(events_path)
    feedback = load_user_feedback(feedback_path)
    reviewed = _load_review_labels(review_labels_path, golden_only=golden_only) if review_labels_path else {}
    joined = join_feedback(events, feedback)
    cases = []
    skipped_unreviewed = 0
    for record in joined:
        if not record.event:
            continue
        for item in record.feedback:
            if only_negative and not is_negative_feedback(item):
                continue
            if category and item.category != category:
                continue
            review_label = reviewed.get(str(item.feedback_id)) or reviewed.get(str(record.event.event_id)) or reviewed.get(str(record.event.session_id))
            if require_reviewed and review_label is None:
                skipped_unreviewed += 1
                continue
            cases.append(_case_from_feedback(record.event.model_dump(mode="json"), item.model_dump(mode="json"), review_label))
            if limit is not None and len(cases) >= limit:
                break
        if limit is not None and len(cases) >= limit:
            break
    return {
        "metadata": {"generated_from_production": True, "sources": [str(events_path), str(feedback_path)], "skipped_unreviewed": skipped_unreviewed},
        "cases": cases,
    }


def write_production_regressions(path: str | Path, dataset: dict[str, Any]) -> None:
    write_regression_dataset(path, dataset)


def append_production_regressions(path: str | Path, dataset: dict[str, Any], dedupe: bool = True) -> dict[str, Any]:
    return append_regression_dataset(path, dataset, dedupe=dedupe)


def _case_from_feedback(event: dict[str, Any], feedback: dict[str, Any], review_label: dict[str, Any] | None = None) -> dict[str, Any]:
    feedback_category = feedback.get("category") or "feedback"
    reviewer_label = feedback.get("reviewer_label") or {}
    if review_label:
        reviewer_label = {**reviewer_label, **(review_label.get("regression_update") or {})}
    expected: dict[str, Any] = {"production_feedback": {"category": feedback_category, "human_reason": feedback.get("comment", ""), "feedback_id": feedback.get("feedback_id")}}
    if reviewer_label.get("required_facts"):
        expected["required_facts"] = reviewer_label.get("required_facts")
    rubric = reviewer_label.get("rubric") or _rubric(feedback)
    tags = list(dict.fromkeys(["production", "feedback", "regression", feedback_category, *(event.get("tags") or [])]))
    metadata = dict(event.get("metadata") or {})
    metadata["production"] = {
        "event_id": event.get("event_id"),
        "session_id": event.get("session_id"),
        "feedback_id": feedback.get("feedback_id"),
        "category": feedback_category,
        "original_agent_version": event.get("agent_version"),
        "source": "production_feedback",
        "review_status": "reviewed" if review_label else "needs_review",
        "fingerprint": _fingerprint(event, feedback),
    }
    if review_label:
        metadata["production"]["review"] = {
            "review_id": review_label.get("review_id"),
            "human_passed": review_label.get("human_passed"),
            "human_score": review_label.get("human_score"),
            "human_failure_type": review_label.get("human_failure_type"),
            "human_reason": review_label.get("human_reason"),
            "failure_owner": review_label.get("failure_owner"),
            "recommended_action": review_label.get("recommended_action"),
            "confidence": review_label.get("confidence"),
            "golden_status": review_label.get("golden_status"),
        }
    return {
        "id": f"production_{_safe_id(str(event.get('event_id')))}_{_safe_id(str(feedback.get('feedback_id')))}",
        "input": event.get("input") or "production feedback case",
        "expected": expected,
        "rubric": rubric,
        "tags": tags,
        "metadata": metadata,
    }


def recommend_policy_updates(dataset: dict[str, Any]) -> dict[str, Any]:
    cases = dataset.get("cases", []) or []
    reviewed = [case for case in cases if ((case.get("metadata") or {}).get("production") or {}).get("review")]
    by_capability: dict[str, int] = {}
    by_risk: dict[str, int] = {}
    evidence = []
    for case in reviewed:
        production = ((case.get("metadata") or {}).get("production") or {})
        review = production.get("review") or {}
        capability = ((case.get("metadata") or {}).get("capability") or "unknown")
        risk = ((case.get("metadata") or {}).get("risk_level") or "unknown")
        by_capability[str(capability)] = by_capability.get(str(capability), 0) + 1
        by_risk[str(risk)] = by_risk.get(str(risk), 0) + 1
        evidence.append({"case_id": case.get("id"), "feedback_id": production.get("feedback_id"), "review_id": review.get("review_id"), "capability": capability, "risk_level": risk, "recommended_action": review.get("recommended_action")})
    recommendations = []
    for capability, count in sorted(by_capability.items()):
        if count >= 1:
            recommendations.append(f"Review promotion gates for capability '{capability}' based on {count} reviewed production regression(s).")
    if any(risk in {"high", "critical"} for risk in by_risk):
        recommendations.append("Require human review before promotion for matching high-risk production feedback segments.")
    if reviewed:
        recommendations.append("Append reviewed production regressions to the active regression library and rerun promotion gates.")
    return {"summary": {"reviewed_cases": len(reviewed), "recommendations": len(recommendations)}, "by_capability": by_capability, "by_risk_level": by_risk, "recommendations": recommendations or ["No reviewed production feedback evidence available for policy updates."], "evidence": evidence}


def write_policy_update_json(path: str | Path, report: dict[str, Any]) -> None:
    write_report_json(path, report)


def write_policy_update_markdown(path: str | Path, report: dict[str, Any]) -> None:
    lines = ["# AgentEval Feedback Policy Recommendations", "", f"- Reviewed cases: {report.get('summary', {}).get('reviewed_cases', 0)}", "", "## Recommendations", ""]
    lines.extend([f"- {item}" for item in report.get("recommendations", []) or []])
    lines.extend(["", "## Evidence", "", "| Case | Feedback | Review | Capability | Risk | Action |", "| --- | --- | --- | --- | --- | --- |"])
    for item in report.get("evidence", []) or []:
        lines.append(f"| `{item.get('case_id')}` | `{item.get('feedback_id')}` | `{item.get('review_id')}` | `{item.get('capability')}` | `{item.get('risk_level')}` | {item.get('recommended_action') or ''} |")
    write_report_text(path, lines)


def _load_review_labels(path: str | Path, *, golden_only: bool) -> dict[str, dict[str, Any]]:
    labels = load_golden_labels(path) if golden_only else load_human_labels(path)
    indexed = {}
    for label in labels:
        payload = label.model_dump(mode="json")
        for key in [label.review_id, label.case_id]:
            if key:
                indexed[str(key)] = payload
        for key in ["feedback_id", "event_id", "session_id"]:
            value = label.regression_update.get(key) or label.policy_update.get(key)
            if value:
                indexed[str(value)] = payload
    return indexed


def _rubric(feedback: dict[str, Any]) -> str:
    category = feedback.get("category") or "user feedback"
    comment = feedback.get("comment") or "No detailed comment provided."
    return f"This regression comes from production {category} feedback. A passing response should address the user need and avoid the reported issue. Human feedback: {comment}"


def _fingerprint(event: dict[str, Any], feedback: dict[str, Any]) -> str:
    payload = json.dumps({"input": event.get("input"), "category": feedback.get("category"), "comment": feedback.get("comment"), "outcome": event.get("outcome")}, ensure_ascii=False, sort_keys=True)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _safe_id(value: str) -> str:
    safe = "".join(char if char.isalnum() or char in {"-", "_"} else "_" for char in value)
    return safe[:64] or "item"
