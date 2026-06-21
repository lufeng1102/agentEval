from __future__ import annotations

import json
from collections import Counter
from pathlib import Path
from typing import Any

from schemas import AgentTrace


def summarize_traces(traces: list[AgentTrace]) -> dict[str, Any]:
    spans = [span for trace in traces for span in trace.spans]
    error_traces = [trace for trace in traces if trace.errors or any(span.error or span.status == "error" for span in trace.spans)]
    return {
        "traces": len(traces),
        "spans": len(spans),
        "sources": dict(Counter(trace.source or "unknown" for trace in traces)),
        "error_traces": len(error_traces),
        "tool_spans": sum(1 for span in spans if span.kind == "tool"),
        "missing_input": sum(1 for trace in traces if trace.input is None and not trace.messages),
        "missing_output": sum(1 for trace in traces if not trace.final_output),
        "by_span_kind": dict(Counter(str(span.kind) for span in spans)),
        "example_trace_ids": [trace.trace_id for trace in traces[:10]],
    }


def build_trace_import_report(source: str, traces: list[AgentTrace]) -> dict[str, Any]:
    return {
        "source": source,
        "summary": summarize_traces(traces),
        "traces": [trace.model_dump(mode="json") for trace in traces],
    }


def write_trace_import_json(path: str | Path, report: dict[str, Any]) -> None:
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")


def write_trace_import_jsonl(path: str | Path, report: dict[str, Any]) -> None:
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", encoding="utf-8") as file:
        for trace in report.get("traces", []) or []:
            file.write(json.dumps(trace, ensure_ascii=False) + "\n")


def write_trace_import_markdown(path: str | Path, report: dict[str, Any]) -> None:
    summary = report.get("summary", {}) or {}
    lines = [
        "# AgentEval Trace Import Summary",
        "",
        f"- Source: `{report.get('source') or 'unknown'}`",
        f"- Traces: {summary.get('traces', 0)}",
        f"- Spans: {summary.get('spans', 0)}",
        f"- Error traces: {summary.get('error_traces', 0)}",
        f"- Tool spans: {summary.get('tool_spans', 0)}",
        f"- Missing input: {summary.get('missing_input', 0)}",
        f"- Missing output: {summary.get('missing_output', 0)}",
        "",
        "## Sources",
        "",
    ]
    lines.extend([f"- `{name}`: {count}" for name, count in (summary.get("sources", {}) or {}).items()] or ["- None"])
    lines.extend(["", "## Span kinds", ""])
    lines.extend([f"- `{name}`: {count}" for name, count in (summary.get("by_span_kind", {}) or {}).items()] or ["- None"])
    lines.extend(["", "## Example trace IDs", ""])
    lines.extend([f"- `{trace_id}`" for trace_id in summary.get("example_trace_ids", [])] or ["- None"])
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text("\n".join(lines) + "\n", encoding="utf-8")
