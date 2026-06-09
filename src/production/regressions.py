from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from evolution.regressions import append_regression_dataset, write_regression_dataset
from production.feedback import join_feedback, load_user_feedback
from production.ingest import load_production_events
from production.summary import is_negative_feedback


def production_feedback_to_regressions(events_path: str | Path, feedback_path: str | Path, *, only_negative: bool = True, limit: int | None = None, category: str | None = None) -> dict[str, Any]:
    events = load_production_events(events_path)
    feedback = load_user_feedback(feedback_path)
    joined = join_feedback(events, feedback)
    cases = []
    for record in joined:
        if not record.event:
            continue
        for item in record.feedback:
            if only_negative and not is_negative_feedback(item):
                continue
            if category and item.category != category:
                continue
            cases.append(_case_from_feedback(record.event.model_dump(mode="json"), item.model_dump(mode="json")))
            if limit is not None and len(cases) >= limit:
                break
        if limit is not None and len(cases) >= limit:
            break
    return {"metadata": {"generated_from_production": True, "sources": [str(events_path), str(feedback_path)]}, "cases": cases}


def write_production_regressions(path: str | Path, dataset: dict[str, Any]) -> None:
    write_regression_dataset(path, dataset)


def append_production_regressions(path: str | Path, dataset: dict[str, Any], dedupe: bool = True) -> dict[str, Any]:
    return append_regression_dataset(path, dataset, dedupe=dedupe)


def _case_from_feedback(event: dict[str, Any], feedback: dict[str, Any]) -> dict[str, Any]:
    feedback_category = feedback.get("category") or "feedback"
    reviewer_label = feedback.get("reviewer_label") or {}
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
        "review_status": "needs_review",
        "fingerprint": _fingerprint(event, feedback),
    }
    return {
        "id": f"production_{_safe_id(str(event.get('event_id')))}_{_safe_id(str(feedback.get('feedback_id')))}",
        "input": event.get("input") or "production feedback case",
        "expected": expected,
        "rubric": rubric,
        "tags": tags,
        "metadata": metadata,
    }


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
