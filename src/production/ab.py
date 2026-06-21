from __future__ import annotations

from pathlib import Path
from typing import Any

from production.report import write_report_json, write_report_text

from production.ingest import load_production_events
from production.models import ProductionEvent
from production.summary import is_negative_feedback, _percentile
from production.feedback import load_user_feedback


def analyze_ab_test(events_path: str | Path, feedback_path: str | Path | None = None, experiment_id: str | None = None, baseline_variant: str | None = None) -> dict[str, Any]:
    events = load_production_events(events_path)
    if experiment_id:
        events = [event for event in events if _experiment(event) == experiment_id]
    feedback = load_user_feedback(feedback_path) if feedback_path else []
    feedback_by_event: dict[str, list[Any]] = {}
    for item in feedback:
        if item.event_id:
            feedback_by_event.setdefault(item.event_id, []).append(item)
    grouped: dict[str, list[ProductionEvent]] = {}
    for event in events:
        grouped.setdefault(_variant(event), []).append(event)
    variants = {name: _variant_metrics(items, feedback_by_event) for name, items in sorted(grouped.items())}
    baseline = baseline_variant or (sorted(variants)[0] if variants else None)
    warnings = []
    if baseline_variant and baseline_variant not in variants:
        warnings.append(f"baseline variant not found: {baseline_variant}")
    baseline_metrics = variants.get(baseline, {})
    comparisons = {name: _delta(baseline_metrics, metrics) for name, metrics in variants.items() if baseline and name != baseline}
    return {
        "events": str(events_path),
        "feedback": str(feedback_path) if feedback_path else None,
        "experiment_id": experiment_id,
        "baseline_variant": baseline,
        "summary": {"events": len(events), "variants": len(variants), "comparisons": len(comparisons), "warnings": len(warnings)},
        "warnings": warnings,
        "variants": variants,
        "comparisons": comparisons,
    }


def write_ab_test_json(path: str | Path, report: dict[str, Any]) -> None:
    write_report_json(path, report)


def write_ab_test_markdown(path: str | Path, report: dict[str, Any]) -> None:
    lines = [
        "# AgentEval Production A/B Report",
        "",
        f"- Events: `{report.get('events')}`",
        f"- Feedback: `{report.get('feedback')}`",
        f"- Experiment: `{report.get('experiment_id') or 'all'}`",
        f"- Baseline variant: `{report.get('baseline_variant')}`",
        f"- Warnings: {len(report.get('warnings') or [])}",
        "",
        "## Variants",
        "",
        "| Variant | Events | Error rate | Negative feedback | Task success | Latency p95 | Tool failure |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for name, metrics in (report.get("variants") or {}).items():
        lines.append(f"| `{name}` | {metrics.get('events', 0)} | {metrics.get('error_rate', 0):.2%} | {metrics.get('negative_feedback_rate', 0):.2%} | {metrics.get('task_success_rate', 0):.2%} | {metrics.get('latency_ms', {}).get('p95', 0):.0f}ms | {metrics.get('tool_failure_rate', 0):.2%} |")
    lines.extend(["", "## Deltas vs baseline", "", "| Variant | Error Δ | Negative feedback Δ | Task success Δ | Latency p95 Δ |", "| --- | ---: | ---: | ---: | ---: |"])
    for name, delta in (report.get("comparisons") or {}).items():
        lines.append(f"| `{name}` | {delta.get('error_rate_delta', 0):.2%} | {delta.get('negative_feedback_rate_delta', 0):.2%} | {delta.get('task_success_rate_delta', 0):.2%} | {delta.get('latency_p95_ms_delta', 0):.0f}ms |")
    write_report_text(path, lines)


def _variant_metrics(events: list[ProductionEvent], feedback_by_event: dict[str, list[Any]]) -> dict[str, Any]:
    latencies = sorted(event.latency_ms for event in events if event.latency_ms is not None)
    tool_calls = [call for event in events for call in event.tool_calls]
    failed_tools = [call for call in tool_calls if call.get("error")]
    task_labeled = [event for event in events if event.task_success is not None]
    feedback = [item for event in events for item in feedback_by_event.get(event.event_id, [])]
    negative = [item for item in feedback if is_negative_feedback(item)]
    return {
        "events": len(events),
        "error_rate": sum(1 for event in events if event.errors) / len(events) if events else 0,
        "negative_feedback_rate": len(negative) / len(feedback) if feedback else 0,
        "feedback": len(feedback),
        "task_success_rate": sum(1 for event in task_labeled if event.task_success) / len(task_labeled) if task_labeled else 0,
        "outcome_coverage": sum(1 for event in events if event.outcome) / len(events) if events else 0,
        "latency_ms": {"p50": _percentile(latencies, 50), "p95": _percentile(latencies, 95)},
        "tool_failure_rate": len(failed_tools) / len(tool_calls) if tool_calls else 0,
    }


def _delta(baseline: dict[str, Any], candidate: dict[str, Any]) -> dict[str, float]:
    return {
        "error_rate_delta": float(candidate.get("error_rate", 0) or 0) - float(baseline.get("error_rate", 0) or 0),
        "negative_feedback_rate_delta": float(candidate.get("negative_feedback_rate", 0) or 0) - float(baseline.get("negative_feedback_rate", 0) or 0),
        "task_success_rate_delta": float(candidate.get("task_success_rate", 0) or 0) - float(baseline.get("task_success_rate", 0) or 0),
        "latency_p95_ms_delta": float((candidate.get("latency_ms") or {}).get("p95", 0) or 0) - float((baseline.get("latency_ms") or {}).get("p95", 0) or 0),
    }


def _variant(event: ProductionEvent) -> str:
    return str(event.variant or event.metadata.get("variant") or "unknown")


def _experiment(event: ProductionEvent) -> str:
    return str(event.experiment_id or event.metadata.get("experiment_id") or "")
