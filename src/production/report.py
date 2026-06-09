from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def write_production_json(path: str | Path, report: dict[str, Any]) -> None:
    _write_json(path, report)


def write_production_jsonl(path: str | Path, report: dict[str, Any]) -> None:
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", encoding="utf-8") as file:
        for event in report.get("events", []) or []:
            file.write(json.dumps(event, ensure_ascii=False) + "\n")


def write_production_markdown(path: str | Path, report: dict[str, Any]) -> None:
    summary = report.get("summary", {}) or {}
    lines = _summary_lines("AgentEval Production Summary", summary)
    lines.extend(["", "## Segments", ""])
    for key in ["by_tag", "by_capability", "by_risk_level", "by_channel", "by_intent", "by_model", "by_agent_version"]:
        lines.append(f"### {key}")
        values = summary.get(key, {}) or {}
        lines.extend([f"- `{name}`: {count}" for name, count in values.items()] or ["- None"])
        lines.append("")
    _write_text(path, lines)


def write_feedback_json(path: str | Path, report: dict[str, Any]) -> None:
    _write_json(path, report)


def write_feedback_markdown(path: str | Path, report: dict[str, Any]) -> None:
    summary = report.get("summary", {}) or {}
    lines = _summary_lines("AgentEval Feedback Summary", summary)
    lines.extend(["", "## Feedback categories", ""])
    lines.extend([f"- `{key}`: {value}" for key, value in (summary.get("feedback_categories", {}) or {}).items()] or ["- None"])
    lines.extend(["", "## Unmatched feedback", "", f"- Count: {summary.get('unmatched_feedback', 0)}"])
    _write_text(path, lines)


def write_coverage_json(path: str | Path, report: dict[str, Any]) -> None:
    _write_json(path, report)


def write_coverage_markdown(path: str | Path, report: dict[str, Any]) -> None:
    summary = report.get("summary", {}) or {}
    lines = [
        "# AgentEval Production Coverage Report",
        "",
        f"- Production events: {summary.get('production_events', 0)}",
        f"- Eval cases: {summary.get('eval_cases', 0)}",
        f"- Uncovered segments: {summary.get('uncovered_segments', 0)}",
        f"- Underrepresented segments: {summary.get('underrepresented_segments', 0)}",
        "",
        "## Uncovered segments",
        "",
    ]
    for dimension, items in (report.get("uncovered", {}) or {}).items():
        lines.append(f"### {dimension}")
        lines.extend([f"- `{item['segment']}`: production={item['production_count']}, eval=0" for item in items] or ["- None"])
        lines.append("")
    lines.extend(["## Underrepresented segments", ""])
    for dimension, items in (report.get("underrepresented", {}) or {}).items():
        lines.append(f"### {dimension}")
        lines.extend([f"- `{item['segment']}`: production={item['production_count']}, eval={item['eval_count']}" for item in items] or ["- None"])
        lines.append("")
    _write_text(path, lines)


def _summary_lines(title: str, summary: dict[str, Any]) -> list[str]:
    return [
        f"# {title}",
        "",
        f"- Events: {summary.get('events', 0)}",
        f"- Error rate: {float(summary.get('error_rate', 0) or 0):.2%}",
        f"- Outcome coverage: {float(summary.get('outcome_coverage', 0) or 0):.2%}",
        f"- Feedback: {summary.get('feedback', 0)}",
        f"- Negative feedback rate: {float(summary.get('negative_feedback_rate', 0) or 0):.2%}",
        f"- Latency p50/p95: {summary.get('latency_ms', {}).get('p50', 0):.0f}ms / {summary.get('latency_ms', {}).get('p95', 0):.0f}ms",
        f"- Tool calls: total={summary.get('tool_calls', {}).get('total', 0)}, failed={summary.get('tool_calls', {}).get('failed', 0)}",
    ]


def _write_json(path: str | Path, payload: dict[str, Any]) -> None:
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _write_text(path: str | Path, lines: list[str]) -> None:
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text("\n".join(lines) + "\n", encoding="utf-8")
