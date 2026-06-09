from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from compare import compare_runs
from evolution.artifacts import load_run_artifacts


SEVERITY_ORDER = {"low": 1, "medium": 2, "high": 3, "critical": 4}


def analyze_impact(baseline: str | Path, candidate: str | Path) -> dict[str, Any]:
    comparison = compare_runs(baseline, candidate)
    candidate_artifacts = load_run_artifacts(candidate)
    candidate_report = candidate_artifacts.report
    newly_failed = comparison.get("newly_failed", []) or []
    failed_case_ids = {str(item).split("::", 1)[0] for item in newly_failed}
    hotspots: list[dict[str, Any]] = []
    delta = comparison.get("delta", {}) or {}
    for dimension, label in [
        ("by_capability", "capability"),
        ("by_risk_level", "risk_level"),
        ("by_tag", "tag"),
        ("by_evaluator", "evaluator"),
        ("by_failure_type", "failure_type"),
    ]:
        group_delta = delta.get(dimension, {}) if dimension in delta else _summary_group_delta(comparison, dimension)
        for key, item in (group_delta or {}).items():
            pass_delta = float(item.get("pass_rate", 0) or 0)
            score_delta = float(item.get("avg_score", 0) or 0)
            if pass_delta < 0 or score_delta < 0 or item.get("results", 0):
                hotspots.append(
                    {
                        "dimension": label,
                        "key": key,
                        "results_delta": int(item.get("results", 0) or 0),
                        "pass_rate_delta": pass_delta,
                        "avg_score_delta": score_delta,
                        "severity": _severity_for_delta(pass_delta, newly_failed=len(newly_failed), key=str(key), dimension=label),
                    }
                )
    hotspots.sort(key=lambda item: (-SEVERITY_ORDER.get(item["severity"], 0), item["pass_rate_delta"], item["dimension"], str(item["key"])))
    tool_impact = _tool_impact(candidate_artifacts.traces, failed_case_ids)
    overall_severity = _overall_severity(delta, newly_failed)
    return {
        "baseline": str(baseline),
        "candidate": str(candidate),
        "summary": {
            "pass_rate_delta": float(delta.get("pass_rate", 0) or 0),
            "avg_score_delta": float(delta.get("avg_score", 0) or 0),
            "newly_failed": len(newly_failed),
            "newly_passed": len(comparison.get("newly_passed", []) or []),
            "severity": overall_severity,
        },
        "hotspots": hotspots,
        "tool_impact": tool_impact,
        "newly_failed": newly_failed,
        "newly_passed": comparison.get("newly_passed", []) or [],
        "candidate_summary": candidate_report.get("summary", {}),
    }


def write_impact_json(path: str | Path, report: dict[str, Any]) -> None:
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")


def write_impact_markdown(path: str | Path, report: dict[str, Any]) -> None:
    summary = report.get("summary", {})
    lines = [
        "# AgentEval Impact Report",
        "",
        f"- Baseline: `{report.get('baseline')}`",
        f"- Candidate: `{report.get('candidate')}`",
        f"- Severity: **{summary.get('severity', 'low')}**",
        f"- Pass-rate delta: {float(summary.get('pass_rate_delta', 0)):.2%}",
        f"- Avg-score delta: {float(summary.get('avg_score_delta', 0)):.2f}",
        f"- Newly failed: {summary.get('newly_failed', 0)}",
        f"- Newly passed: {summary.get('newly_passed', 0)}",
        "",
        "## Hotspots",
        "",
        "| Dimension | Key | Pass-rate Δ | Avg-score Δ | Severity |",
        "| --- | --- | ---: | ---: | --- |",
    ]
    for item in report.get("hotspots", []) or []:
        lines.append(f"| {item['dimension']} | `{item['key']}` | {float(item.get('pass_rate_delta', 0)):.2%} | {float(item.get('avg_score_delta', 0)):.2f} | {item.get('severity', 'low')} |")
    if not report.get("hotspots"):
        lines.append("| None |  | 0.00% | 0.00 | low |")
    lines.extend(["", "## Tool Impact", "", "| Tool | Uses | Associated failures | Failure rate after use |", "| --- | ---: | ---: | ---: |"])
    for item in report.get("tool_impact", []) or []:
        lines.append(f"| `{item['tool']}` | {item['candidate_uses']} | {item['associated_failures']} | {float(item['failure_rate_after_use']):.2%} |")
    if not report.get("tool_impact"):
        lines.append("| None | 0 | 0 | 0.00% |")
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _summary_group_delta(comparison: dict[str, Any], group: str) -> dict[str, dict[str, float | int]]:
    baseline = comparison.get("baseline_summary", {}).get(group, {}) or {}
    candidate = comparison.get("candidate_summary", {}).get(group, {}) or {}
    keys = sorted(set(baseline) | set(candidate))
    return {
        key: {
            "results": int(candidate.get(key, {}).get("results", 0)) - int(baseline.get(key, {}).get("results", 0)),
            "pass_rate": float(candidate.get(key, {}).get("pass_rate", 0)) - float(baseline.get(key, {}).get("pass_rate", 0)),
            "avg_score": float(candidate.get(key, {}).get("avg_score", 0)) - float(baseline.get(key, {}).get("avg_score", 0)),
        }
        for key in keys
    }


def _severity_for_delta(pass_delta: float, newly_failed: int, key: str = "", dimension: str = "") -> str:
    if "safety" in key or (dimension == "risk_level" and key in {"high", "critical"} and pass_delta <= -0.05):
        return "critical"
    if pass_delta <= -0.10 or newly_failed >= 10:
        return "high"
    if pass_delta < 0:
        return "medium"
    return "low"


def _overall_severity(delta: dict[str, Any], newly_failed: list[str]) -> str:
    pass_delta = float(delta.get("pass_rate", 0) or 0)
    if any("::safety" in item for item in newly_failed):
        return "critical"
    if pass_delta <= -0.10 or len(newly_failed) >= 10:
        return "high"
    if pass_delta < 0 or newly_failed:
        return "medium"
    return "low"


def _tool_impact(traces: list[dict[str, Any]], failed_case_ids: set[str]) -> list[dict[str, Any]]:
    tools: dict[str, dict[str, int]] = {}
    for trace in traces:
        case_id = str(trace.get("case_id"))
        names = {str(call.get("name")) for call in trace.get("tool_calls", []) or [] if isinstance(call, dict) and call.get("name")}
        for name in names:
            stats = tools.setdefault(name, {"candidate_uses": 0, "associated_failures": 0})
            stats["candidate_uses"] += 1
            if case_id in failed_case_ids:
                stats["associated_failures"] += 1
    return sorted(
        [
            {
                "tool": name,
                **stats,
                "failure_rate_after_use": stats["associated_failures"] / stats["candidate_uses"] if stats["candidate_uses"] else 0,
            }
            for name, stats in tools.items()
        ],
        key=lambda item: (-item["associated_failures"], item["tool"]),
    )
