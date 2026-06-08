from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def cluster_failures(report: dict[str, Any], traces: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    cases = {case.get("id"): case for case in report.get("cases", []) if isinstance(case, dict)}
    traces_by_case = {trace.get("case_id"): trace for trace in traces or [] if isinstance(trace, dict)}
    clusters: dict[str, dict[str, Any]] = {}
    for result in report.get("results", []) or []:
        if result.get("passed"):
            continue
        case_id = str(result.get("case_id"))
        evaluator = str(result.get("evaluator"))
        failure_type = str(result.get("failure_type") or "")
        reason = str(result.get("failure_reason") or "unknown")
        key = failure_type or f"{evaluator}::{_normalize_reason(reason)}"
        cluster = clusters.setdefault(
            key,
            {
                "id": key,
                "size": 0,
                "cases": [],
                "evaluators": [],
                "failure_types": [],
                "tags": [],
                "stop_reasons": [],
                "tool_names": [],
                "evidence": [],
            },
        )
        cluster["size"] += 1
        _add_unique(cluster["cases"], case_id)
        _add_unique(cluster["evaluators"], evaluator)
        if failure_type:
            _add_unique(cluster["failure_types"], failure_type)
        for tag in cases.get(case_id, {}).get("tags", []) or []:
            _add_unique(cluster["tags"], str(tag))
        trace = traces_by_case.get(case_id) or {}
        dynamic = trace.get("artifacts", {}).get("dynamic", {}) if isinstance(trace.get("artifacts"), dict) else {}
        if dynamic.get("stop_reason"):
            _add_unique(cluster["stop_reasons"], str(dynamic["stop_reason"]))
        for call in trace.get("tool_calls", []) or []:
            if isinstance(call, dict) and call.get("name"):
                _add_unique(cluster["tool_names"], str(call["name"]))
        cluster["evidence"].append({"case_id": case_id, "evaluator": evaluator, "failure_type": failure_type or None, "failure_reason": reason})
    ordered = sorted(clusters.values(), key=lambda item: (-item["size"], item["id"]))
    return {"clusters": ordered, "total_failures": sum(item["size"] for item in ordered)}


def write_failure_clusters_json(path: str | Path, clusters: dict[str, Any]) -> None:
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(clusters, ensure_ascii=False, indent=2), encoding="utf-8")


def write_failure_clusters_markdown(path: str | Path, clusters: dict[str, Any]) -> None:
    lines = ["# AgentEval Failure Mining Report", "", f"- Total failures: {clusters.get('total_failures', 0)}", ""]
    for cluster in clusters.get("clusters", []) or []:
        lines.extend([
            f"## {cluster['id']}",
            "",
            f"- Size: {cluster['size']}",
            f"- Cases: {', '.join(cluster.get('cases', [])) or 'None'}",
            f"- Evaluators: {', '.join(cluster.get('evaluators', [])) or 'None'}",
            f"- Failure types: {', '.join(cluster.get('failure_types', [])) or 'None'}",
            f"- Tags: {', '.join(cluster.get('tags', [])) or 'None'}",
            f"- Stop reasons: {', '.join(cluster.get('stop_reasons', [])) or 'None'}",
            f"- Tool names: {', '.join(cluster.get('tool_names', [])) or 'None'}",
            "",
        ])
        for item in cluster.get("evidence", [])[:5]:
            lines.append(f"  - `{item['case_id']}::{item['evaluator']}` — {item.get('failure_reason') or 'unknown'}")
        lines.append("")
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text("\n".join(lines), encoding="utf-8")


def _normalize_reason(reason: str) -> str:
    return " ".join(reason.lower().split())[:80]


def _add_unique(items: list[str], value: str) -> None:
    if value and value not in items:
        items.append(value)
