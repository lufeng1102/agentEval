from __future__ import annotations

import html
import json
from pathlib import Path
from typing import Any


def write_review_queue_jsonl(path: str | Path, report: dict[str, Any]) -> None:
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", encoding="utf-8") as file:
        for item in report.get("items", []) or []:
            file.write(json.dumps(item, ensure_ascii=False) + "\n")


def write_review_queue_json(path: str | Path, report: dict[str, Any]) -> None:
    _write_json(path, report)


def write_review_queue_html(path: str | Path, report: dict[str, Any]) -> None:
    items = report.get("items", []) or []
    parts = [
        "<!doctype html>",
        '<html lang="en">',
        "<head>",
        '<meta charset="utf-8">',
        '<meta name="viewport" content="width=device-width, initial-scale=1">',
        "<title>AgentEval Annotation Queue</title>",
        "<style>",
        _annotation_stylesheet(),
        "</style>",
        "</head>",
        "<body>",
        "<main>",
        "<header class=\"hero\">",
        "<p class=\"eyebrow\">AgentEval</p>",
        "<h1>Annotation Queue</h1>",
        f"<p>Run: <code>{_escape(report.get('run_dir'))}</code></p>",
        f"<p>Items: <strong>{len(items)}</strong> · Strategies: {_escape(', '.join(report.get('summary', {}).get('strategies', []) or []))}</p>",
        "</header>",
    ]
    for item in items:
        parts.extend(_annotation_item_html(item))
    parts.extend(["</main>", "</body>", "</html>"])
    _write_text(path, parts)


def write_review_queue_markdown(path: str | Path, report: dict[str, Any]) -> None:
    lines = [
        "# AgentEval Human Review Queue",
        "",
        f"- Run: `{report.get('run_dir')}`",
        f"- Items: {len(report.get('items', []) or [])}",
        f"- Strategies: {', '.join(report.get('summary', {}).get('strategies', []) or [])}",
        "",
    ]
    for item in report.get("items", []) or []:
        lines.extend([
            f"## {item.get('case_id')} / repeat {item.get('repeat_index', 0)}",
            "",
            f"- Review ID: `{item.get('review_id')}`",
            f"- Priority: **{item.get('priority')}**",
            f"- Strategies: {', '.join(item.get('strategies', []) or [])}",
            f"- Tags: {', '.join(item.get('tags', []) or []) or 'None'}",
            f"- Suggested reason: {item.get('suggested_reason') or 'N/A'}",
            "",
            "### Agent output",
            "",
            "```text",
            str(item.get("agent_output") or ""),
            "```",
            "",
            "### Evaluator results",
            "",
        ])
        results = item.get("results", []) or []
        if not results:
            lines.append("No evaluator results.")
        else:
            lines.extend(["| Evaluator | Passed | Score | Failure type | Reason |", "| --- | --- | ---: | --- | --- |"])
            for result in results:
                lines.append(f"| `{result.get('evaluator')}` | {result.get('passed')} | {float(result.get('score', 0) or 0):.2f} | `{result.get('failure_type') or ''}` | {str(result.get('failure_reason') or '')[:160]} |")
        lines.append("")
    _write_text(path, lines)


def write_human_review_json(path: str | Path, report: dict[str, Any]) -> None:
    _write_json(path, report)


def write_human_review_markdown(path: str | Path, report: dict[str, Any]) -> None:
    summary = report.get("summary", {}) or {}
    lines = [
        "# AgentEval Human Review Summary",
        "",
        f"- Queue items: {summary.get('queue_items', 0)}",
        f"- Labeled: {summary.get('labeled', 0)}",
        f"- Missing labels: {summary.get('missing_labels', 0)}",
        f"- Human pass rate: {float(summary.get('human_pass_rate', 0) or 0):.2%}",
        f"- Human average score: {float(summary.get('human_avg_score', 0) or 0):.2f}",
        f"- False passes: {summary.get('false_passes', 0)}",
        f"- False fails: {summary.get('false_fails', 0)}",
        "",
        "## Failure types",
        "",
        "| Failure type | Count |",
        "| --- | ---: |",
    ]
    for key, count in (report.get("failure_types", {}) or {}).items():
        lines.append(f"| `{key}` | {count} |")
    if not report.get("failure_types"):
        lines.append("| None | 0 |")
    lines.extend(["", "## Failure owners", ""])
    lines.extend([f"- `{key}`: {value}" for key, value in (report.get("failure_owners", {}) or {}).items()] or ["- None"])
    lines.extend(["", "## Recommended actions", ""])
    lines.extend([f"- `{key}`: {value}" for key, value in (report.get("recommended_actions", {}) or {}).items()] or ["- None"])
    lines.extend(["", "## Mismatches", ""])
    mismatches = [record for record in report.get("records", []) or [] if record.get("mismatch")]
    if not mismatches:
        lines.append("No automated/human mismatches.")
    else:
        lines.extend(["| Case | Mismatch | Human score | Automated score | Reason |", "| --- | --- | ---: | ---: | --- |"])
        for record in mismatches:
            item = record.get("item", {})
            label = record.get("label", {}) or {}
            lines.append(f"| `{item.get('case_id')}` | `{record.get('mismatch')}` | {float(label.get('human_score', 0) or 0):.2f} | {float(record.get('automated_score', 0) or 0):.2f} | {str(label.get('human_reason') or '')[:160]} |")
    _write_text(path, lines)


def write_calibration_json(path: str | Path, report: dict[str, Any]) -> None:
    _write_json(path, report)


def write_calibration_markdown(path: str | Path, report: dict[str, Any]) -> None:
    summary = report.get("summary", {}) or {}
    lines = [
        "# AgentEval Judge Calibration Report",
        "",
        f"- Run: `{report.get('run_dir')}`",
        f"- Labeled cases: {summary.get('labeled_cases', 0)}",
        f"- Agreement rate: {float(summary.get('agreement_rate', 0) or 0):.2%}",
        f"- Precision: {float(summary.get('precision', 0) or 0):.2%}",
        f"- Recall: {float(summary.get('recall', 0) or 0):.2%}",
        f"- F1: {float(summary.get('f1', 0) or 0):.2%}",
        f"- Mean absolute score error: {float(summary.get('mean_absolute_score_error', 0) or 0):.2f}",
        f"- False passes: {summary.get('false_passes', 0)}",
        f"- False fails: {summary.get('false_fails', 0)}",
        "",
        "## By evaluator",
        "",
        "| Evaluator | Cases | Agreement | Precision | Recall | F1 | MAE |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for evaluator, stats in (report.get("by_evaluator", {}) or {}).items():
        lines.append(f"| `{evaluator}` | {stats.get('cases', 0)} | {float(stats.get('agreement_rate', 0) or 0):.2%} | {float(stats.get('precision', 0) or 0):.2%} | {float(stats.get('recall', 0) or 0):.2%} | {float(stats.get('f1', 0) or 0):.2%} | {float(stats.get('mean_absolute_score_error', 0) or 0):.2f} |")
    lines.extend(["", "## Top disagreements", ""])
    disagreements = report.get("top_disagreements", []) or []
    if not disagreements:
        lines.append("No disagreements found.")
    else:
        lines.extend(["| Case | Evaluator | Human | Auto | Score gap |", "| --- | --- | --- | --- | ---: |"])
        for item in disagreements:
            lines.append(f"| `{item.get('case_id')}` | `{item.get('evaluator')}` | {item.get('human_passed')} | {item.get('automated_passed')} | {float(item.get('score_gap', 0) or 0):.2f} |")
    lines.extend(["", "## Recommendations", ""])
    lines.extend([f"- {item}" for item in report.get("recommendations", [])] or ["None"])
    _write_text(path, lines)


def write_disagreement_json(path: str | Path, report: dict[str, Any]) -> None:
    _write_json(path, report)


def write_disagreement_markdown(path: str | Path, report: dict[str, Any]) -> None:
    summary = report.get("summary", {}) or {}
    lines = [
        "# AgentEval Review Disagreement Report",
        "",
        f"- Queue items: {summary.get('queue_items', 0)}",
        f"- Labels: {summary.get('labels', 0)}",
        f"- Labeled items: {summary.get('labeled_items', 0)}",
        f"- Duplicate-labeled items: {summary.get('duplicate_labeled_items', 0)}",
        f"- Reviewer agreement rate: {float(summary.get('reviewer_agreement_rate', 0) or 0):.2%}",
        f"- Needs adjudication: {summary.get('needs_adjudication', 0)}",
        f"- Automated/human disagreements: {summary.get('automated_human_disagreements', 0)}",
        f"- False passes: {summary.get('false_passes', 0)}",
        f"- False fails: {summary.get('false_fails', 0)}",
        "",
        "## Coverage by reviewer",
        "",
    ]
    lines.extend([f"- `{key}`: {value}" for key, value in (report.get("coverage_by_reviewer", {}) or {}).items()] or ["- None"])
    lines.extend(["", "## Items needing adjudication", ""])
    adjudication = report.get("needs_adjudication_items", []) or []
    if not adjudication:
        lines.append("No adjudication needed.")
    else:
        lines.extend(["| Review ID | Case | Reason | Labels |", "| --- | --- | --- | ---: |"])
        for item in adjudication:
            lines.append(f"| `{item.get('review_id')}` | `{item.get('case_id')}` | {item.get('reason')} | {len(item.get('labels', []) or [])} |")
    lines.extend(["", "## Top automated/human disagreements", ""])
    disagreements = report.get("top_disagreements", []) or []
    if not disagreements:
        lines.append("No automated/human disagreements.")
    else:
        lines.extend(["| Review ID | Case | Mismatch | Human | Auto | Reviewer | Reason |", "| --- | --- | --- | --- | --- | --- | --- |"])
        for item in disagreements:
            lines.append(f"| `{item.get('review_id')}` | `{item.get('case_id')}` | `{item.get('mismatch')}` | {item.get('human_passed')} ({float(item.get('human_score', 0) or 0):.2f}) | {item.get('automated_passed')} ({float(item.get('automated_score', 0) or 0):.2f}) | `{item.get('reviewer') or 'unknown'}` | {str(item.get('human_reason') or '')[:160]} |")
    _write_text(path, lines)


def _label_template(item: dict[str, Any]) -> dict[str, Any]:
    return {
        "schema_version": "review_label_v1",
        "review_id": item.get("review_id"),
        "case_id": item.get("case_id"),
        "repeat_index": int(item.get("repeat_index", 0) or 0),
        "human_passed": False,
        "human_score": 0.0,
        "human_failure_type": None,
        "human_reason": "",
        "rubric_dimension_scores": {},
        "failure_owner": "unclear",
        "valid_alternative_solution": False,
        "rubric_clarity_score": None,
        "recommended_action": None,
        "adjudication_status": None,
        "label_status": "submitted",
        "confidence": None,
        "reviewer_notes": None,
        "golden_candidate": False,
        "golden_status": None,
        "policy_update": {},
        "regression_update": {},
        "reviewer": None,
        "reviewed_at": None,
    }


def _annotation_item_html(item: dict[str, Any]) -> list[str]:
    metadata = item.get("metadata", {}) or {}
    results = item.get("results", []) or []
    template = json.dumps(_label_template(item), ensure_ascii=False, indent=2)
    lines = [
        '<section class="item">',
        '<div class="item-header">',
        f"<div><p class=\"eyebrow\">{_escape(item.get('priority'))} priority</p><h2>{_escape(item.get('case_id'))} <span>/ repeat {_escape(item.get('repeat_index', 0))}</span></h2></div>",
        f"<code>{_escape(item.get('review_id'))}</code>",
        "</div>",
        '<div class="chips">',
        *[f"<span>{_escape(value)}</span>" for value in item.get("strategies", []) or []],
        *[f"<span>tag:{_escape(value)}</span>" for value in item.get("tags", []) or []],
        f"<span>capability:{_escape(metadata.get('capability') or 'unknown')}</span>",
        f"<span>risk:{_escape(metadata.get('risk_level') or 'unknown')}</span>",
        "</div>",
        f"<p class=\"reason\"><strong>Suggested focus:</strong> {_escape(item.get('suggested_reason') or 'N/A')}</p>",
        '<div class="grid">',
        _details("Input", item.get("input")),
        _details("Expected", item.get("expected") or {}),
        _details("Rubric", item.get("rubric") or ""),
        _details("Agent output", item.get("agent_output") or ""),
        _details("Messages", item.get("messages") or []),
        _details("Tool calls", item.get("tool_calls") or []),
        _details("Environment", item.get("environment") or {}),
        _results_table(results),
        _details("Copyable label JSONL record", template, preformatted=True),
        "</div>",
        "</section>",
    ]
    return lines


def _results_table(results: list[dict[str, Any]]) -> str:
    if not results:
        return '<details open><summary>Evaluator results</summary><p>No evaluator results.</p></details>'
    rows = ["<table><thead><tr><th>Evaluator</th><th>Passed</th><th>Score</th><th>Failure type</th><th>Reason</th></tr></thead><tbody>"]
    for result in results:
        rows.append(
            "<tr>"
            f"<td><code>{_escape(result.get('evaluator'))}</code></td>"
            f"<td>{_escape(result.get('passed'))}</td>"
            f"<td>{float(result.get('score', 0) or 0):.2f}</td>"
            f"<td>{_escape(result.get('failure_type') or '')}</td>"
            f"<td>{_escape(result.get('failure_reason') or '')}</td>"
            "</tr>"
        )
    rows.append("</tbody></table>")
    return f"<details open><summary>Evaluator results</summary>{''.join(rows)}</details>"


def _details(title: str, value: Any, *, preformatted: bool = False) -> str:
    if not preformatted and not isinstance(value, str):
        value = json.dumps(value, ensure_ascii=False, indent=2)
    content = str(value or "")
    return f"<details open><summary>{_escape(title)}</summary><pre>{_escape(content)}</pre></details>"


def _escape(value: Any) -> str:
    return html.escape(str(value if value is not None else ""), quote=True)


def _annotation_stylesheet() -> str:
    return """
:root { color-scheme: light; font-family: Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; background: #f6f7fb; color: #162033; }
body { margin: 0; }
main { max-width: 1180px; margin: 0 auto; padding: 32px 20px 56px; }
.hero, .item { background: white; border: 1px solid #dbe1ea; border-radius: 18px; box-shadow: 0 10px 28px rgba(20, 32, 51, 0.07); }
.hero { padding: 28px; margin-bottom: 22px; }
.hero h1 { margin: 0 0 8px; font-size: 34px; }
.eyebrow { margin: 0 0 6px; color: #667085; font-size: 12px; font-weight: 700; letter-spacing: .08em; text-transform: uppercase; }
.item { padding: 22px; margin: 18px 0; }
.item-header { display: flex; justify-content: space-between; gap: 18px; align-items: flex-start; }
h2 { margin: 0; font-size: 24px; }
h2 span { color: #667085; font-weight: 500; }
code { background: #eef2f7; border-radius: 7px; padding: 2px 6px; }
.chips { display: flex; flex-wrap: wrap; gap: 8px; margin: 14px 0; }
.chips span { background: #ecfdf3; color: #05603a; border: 1px solid #abefc6; padding: 4px 9px; border-radius: 999px; font-size: 12px; font-weight: 700; }
.reason { color: #344054; }
.grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(320px, 1fr)); gap: 14px; }
details { background: #fbfcfe; border: 1px solid #e4e7ec; border-radius: 12px; padding: 12px; overflow: auto; }
summary { cursor: pointer; font-weight: 800; margin-bottom: 8px; }
pre { white-space: pre-wrap; word-break: break-word; font-size: 12px; line-height: 1.45; margin: 0; }
table { width: 100%; border-collapse: collapse; font-size: 13px; }
th, td { border-bottom: 1px solid #e4e7ec; padding: 8px; text-align: left; vertical-align: top; }
th { color: #475467; }
""".strip()


def _write_text(path: str | Path, lines: list[str]) -> None:
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _write_json(path: str | Path, payload: dict[str, Any]) -> None:
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
