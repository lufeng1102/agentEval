from __future__ import annotations

from collections import Counter, defaultdict
from statistics import median
from typing import Any

from production.models import ProductionEvent, UserFeedback


def summarize_production(events: list[ProductionEvent], feedback: list[UserFeedback] | None = None) -> dict[str, Any]:
    feedback = feedback or []
    latencies = sorted(event.latency_ms for event in events if event.latency_ms is not None)
    tool_calls = [call for event in events for call in event.tool_calls]
    failed_tools = [call for call in tool_calls if call.get("error")]
    negative = [item for item in feedback if is_negative_feedback(item)]
    return {
        "events": len(events),
        "errors": sum(len(event.errors) for event in events),
        "error_rate": sum(1 for event in events if event.errors) / len(events) if events else 0,
        "with_outcome": sum(1 for event in events if event.outcome),
        "outcome_coverage": sum(1 for event in events if event.outcome) / len(events) if events else 0,
        "task_success_rate": sum(1 for event in events if event.task_success is True) / sum(1 for event in events if event.task_success is not None) if any(event.task_success is not None for event in events) else 0,
        "feedback": len(feedback),
        "feedback_rate": len({item.event_id for item in feedback if item.event_id}) / len(events) if events else 0,
        "negative_feedback": len(negative),
        "negative_feedback_rate": len(negative) / len(feedback) if feedback else 0,
        "latency_ms": {"p50": _percentile(latencies, 50), "p95": _percentile(latencies, 95)},
        "tool_calls": {"total": len(tool_calls), "failed": len(failed_tools)},
        "by_tag": dict(Counter(tag for event in events for tag in event.tags)),
        "by_capability": _metadata_counts(events, "capability"),
        "by_risk_level": _metadata_counts(events, "risk_level"),
        "by_channel": _metadata_counts(events, "channel"),
        "by_intent": _metadata_counts(events, "intent"),
        "by_locale": _metadata_counts(events, "locale"),
        "by_model": dict(Counter(event.model or "unknown" for event in events)),
        "by_agent_version": dict(Counter(event.agent_version or "unknown" for event in events)),
        "by_variant": dict(Counter(event.variant or event.metadata.get("variant") or "unknown" for event in events)),
        "by_experiment": dict(Counter(event.experiment_id or event.metadata.get("experiment_id") or "unknown" for event in events)),
        "feedback_categories": dict(Counter(item.category or "uncategorized" for item in feedback)),
        "example_event_ids": [event.event_id for event in events[:10]],
    }


def is_negative_feedback(item: UserFeedback) -> bool:
    if item.user_reported_failure:
        return True
    if item.sentiment and item.sentiment.lower() == "negative":
        return True
    return item.rating is not None and item.rating <= 0


def _metadata_counts(events: list[ProductionEvent], key: str) -> dict[str, int]:
    return dict(Counter(str(event.metadata.get(key)) for event in events if event.metadata.get(key) is not None))


def _percentile(values: list[float], percentile: int) -> float:
    if not values:
        return 0.0
    index = min(len(values) - 1, round((percentile / 100) * (len(values) - 1)))
    return values[index]
