from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from production.ingest import _load_payloads, load_production_events
from production.models import JoinedProductionRecord, ProductionEvent, UserFeedback
from production.summary import is_negative_feedback, summarize_production


def load_user_feedback(path: str | Path) -> list[UserFeedback]:
    payloads = _load_payloads(path, "feedback")
    return [UserFeedback.model_validate(_normalize_feedback(item)) for item in payloads]


def join_feedback(events: list[ProductionEvent], feedback: list[UserFeedback]) -> list[JoinedProductionRecord]:
    by_event = {event.event_id: event for event in events}
    by_session: dict[str, ProductionEvent] = {event.session_id: event for event in events if event.session_id}
    feedback_by_event: dict[str, list[UserFeedback]] = {event.event_id: [] for event in events}
    unmatched: list[JoinedProductionRecord] = []
    for item in feedback:
        event = by_event.get(item.event_id or "") or by_session.get(item.session_id or "")
        if event:
            feedback_by_event.setdefault(event.event_id, []).append(item)
        else:
            unmatched.append(JoinedProductionRecord(event=None, feedback=[item], matched=False))
    joined = [JoinedProductionRecord(event=event, feedback=feedback_by_event.get(event.event_id, []), matched=True) for event in events]
    return joined + unmatched


def ingest_feedback(events_path: str | Path, feedback_path: str | Path) -> dict[str, Any]:
    events = load_production_events(events_path)
    feedback = load_user_feedback(feedback_path)
    joined = join_feedback(events, feedback)
    unmatched = [record for record in joined if not record.matched]
    matched_feedback = sum(len(record.feedback) for record in joined if record.matched)
    return {
        "events_source": str(events_path),
        "feedback_source": str(feedback_path),
        "summary": {
            **summarize_production(events, feedback),
            "matched_feedback": matched_feedback,
            "unmatched_feedback": sum(len(record.feedback) for record in unmatched),
            "feedback_coverage": sum(1 for record in joined if record.matched and record.feedback) / len(events) if events else 0,
        },
        "events": [event.model_dump(mode="json") for event in events],
        "feedback": [item.model_dump(mode="json") for item in feedback],
        "joined": [record.model_dump(mode="json") for record in joined],
    }


def _normalize_feedback(item: dict[str, Any]) -> dict[str, Any]:
    data = dict(item)
    if not data.get("feedback_id"):
        payload = json.dumps({"event_id": data.get("event_id"), "session_id": data.get("session_id"), "comment": data.get("comment"), "timestamp": data.get("timestamp")}, ensure_ascii=False, sort_keys=True)
        data["feedback_id"] = "fb_" + hashlib.sha1(payload.encode("utf-8")).hexdigest()[:16]
    data.setdefault("comment", "")
    data.setdefault("user_reported_failure", False)
    data.setdefault("reviewer_label", {})
    data.setdefault("metadata", {})
    return data


__all__ = ["ingest_feedback", "is_negative_feedback", "join_feedback", "load_user_feedback"]
