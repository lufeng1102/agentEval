from __future__ import annotations

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
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text("\n".join(lines) + "\n", encoding="utf-8")


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
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text("\n".join(lines) + "\n", encoding="utf-8")


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
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text("\n".join(lines) + "\n", encoding="utf-8")


def _write_json(path: str | Path, payload: dict[str, Any]) -> None:
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
