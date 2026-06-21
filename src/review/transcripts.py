from __future__ import annotations

import json
from collections import defaultdict
from html import escape
from pathlib import Path
from typing import Any

from evolution.artifacts import load_run_artifacts


def build_transcript_review(
    run_dir: str | Path,
    *,
    case_ids: list[str] | None = None,
    evaluators: list[str] | None = None,
    failed_only: bool = True,
    limit: int | None = None,
    max_message_chars: int = 4000,
    max_tool_output_chars: int = 2000,
) -> dict[str, Any]:
    artifacts = load_run_artifacts(run_dir)
    selected_cases = set(case_ids or [])
    selected_evaluators = set(evaluators or [])
    cases = {str(case.get("id")): case for case in artifacts.report.get("cases", []) or [] if isinstance(case, dict)}
    results_by_key: dict[tuple[str, int], list[dict[str, Any]]] = defaultdict(list)
    for result in artifacts.report.get("results", []) or []:
        if not isinstance(result, dict):
            continue
        if selected_evaluators and str(result.get("evaluator")) not in selected_evaluators:
            continue
        key = (str(result.get("case_id")), int(result.get("repeat_index", 0) or 0))
        results_by_key[key].append(result)

    trace_by_key = {(str(trace.get("case_id")), int(trace.get("repeat_index", 0) or 0)): trace for trace in artifacts.traces if isinstance(trace, dict)}
    keys = sorted(set(trace_by_key) | set(results_by_key))
    items = []
    for key in keys:
        case_id, repeat_index = key
        if selected_cases and case_id not in selected_cases:
            continue
        results = results_by_key.get(key, [])
        if selected_evaluators and not results:
            results = [
                {
                    "case_id": case_id,
                    "repeat_index": repeat_index,
                    "evaluator": evaluator,
                    "score": 0,
                    "passed": False,
                    "failure_type": "missing_evaluator_result",
                    "failure_reason": "No evaluator result was found for this case/repeat.",
                }
                for evaluator in sorted(selected_evaluators)
            ]
        failed = any(not result.get("passed") for result in results)
        if failed_only and not failed:
            continue
        trace = trace_by_key.get(key, {})
        case = cases.get(case_id, {})
        item = _build_item(case, trace, results, repeat_index, max_message_chars, max_tool_output_chars)
        items.append(item)

    items.sort(key=lambda item: (not item["failed"], -_risk_rank(item.get("metadata", {}).get("risk_level")), item["case_id"], item["repeat_index"]))
    if limit is not None:
        items = items[: max(0, limit)]
    return {
        "run_dir": str(run_dir),
        "manifest": artifacts.manifest,
        "summary": {
            "items": len(items),
            "failed_only": failed_only,
            "case_filters": case_ids or [],
            "evaluator_filters": evaluators or [],
            "failed_items": sum(1 for item in items if item["failed"]),
        },
        "items": items,
    }


def write_transcript_review_json(path: str | Path, report: dict[str, Any]) -> None:
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")


def write_transcript_review_html(path: str | Path, report: dict[str, Any]) -> None:
    summary = report.get("summary", {}) or {}
    cards = []
    for item in report.get("items", []) or []:
        result_rows = "".join(
            f"<tr><td><code>{escape(str(result.get('evaluator')))}</code></td><td>{escape(str(result.get('passed')))}</td><td>{float(result.get('score', 0) or 0):.2f}</td><td>{escape(str(result.get('failure_type') or ''))}</td><td>{escape(str(result.get('failure_reason') or ''))}</td></tr>"
            for result in item.get("results", []) or []
        ) or "<tr><td colspan='5'>No evaluator results</td></tr>"
        messages = "".join(
            f"<details><summary>{escape(str(message.get('role', 'unknown')))}</summary><pre>{escape(_stringify(message.get('content')))}</pre></details>"
            for message in item.get("messages", []) or []
        )
        tools = "".join(
            f"<details><summary>{escape(str(call.get('name')))} error={escape(str(call.get('error') or 'None'))}</summary><pre>{escape(json.dumps(call, ensure_ascii=False, indent=2))}</pre></details>"
            for call in item.get("tool_calls", []) or []
        ) or "<p>No tool calls.</p>"
        environment = item.get("environment") or {}
        screenshots = []
        for check in environment.get("browser", []) or []:
            if check.get("screenshot_path"):
                screenshots.append(f"<li><code>{escape(str(check.get('screenshot_path')))}</code></li>")
        screenshot_block = f"<h4>Screenshots</h4><ul>{''.join(screenshots)}</ul>" if screenshots else ""
        cards.append(
            "<section class='card'>"
            f"<h2>{escape(str(item.get('case_id')))} / repeat {escape(str(item.get('repeat_index', 0)))}</h2>"
            f"<p><strong>Failed:</strong> {escape(str(item.get('failed')))} &nbsp; <strong>Focus:</strong> {escape(str(item.get('suggested_focus') or 'N/A'))}</p>"
            f"<p><strong>Tags:</strong> {escape(', '.join(item.get('tags', []) or []) or 'None')}</p>"
            "<h3>Evaluator results</h3><table><tr><th>Evaluator</th><th>Passed</th><th>Score</th><th>Type</th><th>Reason</th></tr>"
            f"{result_rows}</table>"
            f"<h3>Conversation</h3>{messages}"
            f"<h3>Final output</h3><pre>{escape(str(item.get('final_output') or ''))}</pre>"
            f"<h3>Tool calls</h3>{tools}"
            f"{screenshot_block}"
            "</section>"
        )
    html = [
        "<!doctype html><html><head><meta charset='utf-8'><title>AgentEval Transcript Workbench</title>",
        "<style>body{font-family:-apple-system,BlinkMacSystemFont,Segoe UI,sans-serif;margin:2rem;background:#f6f8fa;color:#182230}.card{background:white;border:1px solid #e4e7ec;border-radius:16px;padding:1rem;margin:1rem 0}table{border-collapse:collapse;width:100%}th,td{padding:.55rem;border-bottom:1px solid #e4e7ec;text-align:left;vertical-align:top}th{background:#f9fafb}pre{white-space:pre-wrap;background:#101828;color:#f2f4f7;padding:1rem;border-radius:10px;overflow:auto}code{background:#eef2ff;padding:.12rem .35rem;border-radius:6px}details{margin:.5rem 0}</style>",
        "</head><body>",
        "<h1>AgentEval Transcript Workbench</h1>",
        f"<p>Run: <code>{escape(str(report.get('run_dir')))}</code></p>",
        f"<p>Items: {summary.get('items', 0)}; failed items: {summary.get('failed_items', 0)}; failed-only: {summary.get('failed_only')}</p>",
        *cards,
        "</body></html>",
    ]
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text("\n".join(html), encoding="utf-8")


def write_transcript_review_markdown(path: str | Path, report: dict[str, Any]) -> None:
    summary = report.get("summary", {}) or {}
    lines = [
        "# AgentEval Transcript Review",
        "",
        f"- Run: `{report.get('run_dir')}`",
        f"- Items: {summary.get('items', 0)}",
        f"- Failed only: {summary.get('failed_only')}",
        f"- Failed items: {summary.get('failed_items', 0)}",
        "",
    ]
    for item in report.get("items", []) or []:
        lines.extend(_item_markdown(item))
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _build_item(case: dict[str, Any], trace: dict[str, Any], results: list[dict[str, Any]], repeat_index: int, max_message_chars: int, max_tool_output_chars: int) -> dict[str, Any]:
    artifacts = trace.get("artifacts", {}) if isinstance(trace.get("artifacts", {}), dict) else {}
    dynamic = artifacts.get("dynamic", {}) if isinstance(artifacts.get("dynamic", {}), dict) else {}
    environment = artifacts.get("environment", {}) if isinstance(artifacts.get("environment", {}), dict) else {}
    failed_results = [result for result in results if not result.get("passed")]
    return {
        "case_id": str(trace.get("case_id") or case.get("id")),
        "repeat_index": repeat_index,
        "failed": bool(failed_results),
        "input": case.get("input"),
        "expected": case.get("expected") or {},
        "rubric": case.get("rubric"),
        "tags": case.get("tags") or [],
        "metadata": case.get("metadata") or {},
        "messages": [_truncate_message(message, max_message_chars) for message in trace.get("messages", []) or []],
        "final_output": _truncate_text(str(trace.get("final_output", "")), max_message_chars),
        "tool_calls": [_truncate_tool_call(call, max_tool_output_chars) for call in trace.get("tool_calls", []) or []],
        "results": results,
        "suggested_focus": _suggested_focus(failed_results),
        "dynamic": _dynamic_summary(dynamic),
        "environment": _environment_summary(environment),
        "errors": trace.get("errors", []) or [],
    }


def _item_markdown(item: dict[str, Any]) -> list[str]:
    title = f"## {item.get('case_id')} / repeat {item.get('repeat_index', 0)}"
    lines = [title, "", f"- Failed: **{item.get('failed')}**", f"- Tags: {', '.join(item.get('tags', []) or []) or 'None'}", f"- Suggested focus: {item.get('suggested_focus') or 'N/A'}", ""]
    if item.get("results"):
        lines.extend(["### Evaluator results", "", "| Evaluator | Passed | Score | Failure type | Reason |", "| --- | --- | ---: | --- | --- |"])
        for result in item.get("results", []) or []:
            lines.append(f"| `{result.get('evaluator')}` | {result.get('passed')} | {float(result.get('score', 0) or 0):.2f} | `{result.get('failure_type') or ''}` | {_escape_cell(str(result.get('failure_reason') or '')[:220])} |")
        lines.append("")
    lines.extend(["### Conversation", ""])
    for message in item.get("messages", []) or []:
        lines.extend([f"**{message.get('role', 'unknown')}**", "", "```text", _stringify(message.get("content")), "```", ""])
    lines.extend(["### Final output", "", "```text", str(item.get("final_output") or ""), "```", ""])
    if item.get("tool_calls"):
        lines.extend(["### Tool calls", ""])
        for call in item.get("tool_calls", []) or []:
            lines.extend([f"- `{call.get('name')}` error={call.get('error') or 'None'}", "", "```json", json.dumps(call.get("input", {}), ensure_ascii=False, indent=2), "```", ""])
            if call.get("output") is not None:
                lines.extend(["Output:", "", "```text", _stringify(call.get("output")), "```", ""])
    dynamic = item.get("dynamic") or {}
    if dynamic:
        lines.extend(["### Dynamic scenario", "", f"- Stop reason: `{dynamic.get('stop_reason')}`", f"- Turns: {dynamic.get('turns', 0)}", f"- Simulator turns: {dynamic.get('simulator_turns', 0)}", ""])
    environment = item.get("environment") or {}
    if environment:
        lines.extend(["### Environment", "", "```json", json.dumps(environment, ensure_ascii=False, indent=2), "```", ""])
    return lines


def _dynamic_summary(dynamic: dict[str, Any]) -> dict[str, Any]:
    if not dynamic:
        return {}
    return {
        "stop_reason": dynamic.get("stop_reason"),
        "turns": len(dynamic.get("turns", []) or []),
        "simulator_turns": len(dynamic.get("simulator_turns", []) or []),
        "state_history": len(dynamic.get("state_history", []) or []),
        "final_state": dynamic.get("final_state"),
    }


def _environment_summary(environment: dict[str, Any]) -> dict[str, Any]:
    if not environment:
        return {}
    return {
        "summary": environment.get("summary") or {},
        "diff": environment.get("diff") or {},
        "commands": environment.get("commands") or [],
        "database": environment.get("database") or [],
        "http": environment.get("http") or [],
        "browser": environment.get("browser") or [],
    }


def _suggested_focus(failed_results: list[dict[str, Any]]) -> str | None:
    reasons = [str(result.get("failure_reason")) for result in failed_results if result.get("failure_reason")]
    if reasons:
        return "; ".join(reasons[:3])
    types = [str(result.get("failure_type")) for result in failed_results if result.get("failure_type")]
    return ", ".join(types[:3]) if types else None


def _truncate_message(message: dict[str, Any], limit: int) -> dict[str, Any]:
    item = dict(message)
    item["content"] = _truncate_text(_stringify(item.get("content")), limit)
    return item


def _truncate_tool_call(call: dict[str, Any], limit: int) -> dict[str, Any]:
    item = dict(call)
    if "output" in item:
        item["output"] = _truncate_text(_stringify(item.get("output")), limit)
    return item


def _truncate_text(text: str, limit: int) -> str:
    if limit <= 0 or len(text) <= limit:
        return text
    return text[:limit] + f"\n... [truncated {len(text) - limit} chars]"


def _stringify(value: Any) -> str:
    if isinstance(value, str):
        return value
    return json.dumps(value, ensure_ascii=False, indent=2)


def _escape_cell(value: str) -> str:
    return value.replace("|", "/").replace("\n", " ")


def _risk_rank(value: Any) -> int:
    return {"critical": 4, "high": 3, "medium": 2, "low": 1}.get(str(value).lower(), 0)
