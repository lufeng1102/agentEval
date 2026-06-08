from __future__ import annotations

import json
from html import escape
from pathlib import Path
from typing import Any

from evolution.artifacts import RunArtifacts, version_delta


def compare_runs(baseline_dir: str | Path, candidate_dir: str | Path) -> dict[str, Any]:
    baseline_path = Path(baseline_dir)
    candidate_path = Path(candidate_dir)
    baseline = _load_report(baseline_path)
    candidate = _load_report(candidate_path)
    agent_delta = version_delta(
        RunArtifacts(run_dir=baseline_path, report=baseline, traces=[], manifest=_load_manifest(baseline_path)),
        RunArtifacts(run_dir=candidate_path, report=candidate, traces=[], manifest=_load_manifest(candidate_path)),
    )
    baseline_summary = baseline["summary"]
    candidate_summary = candidate["summary"]
    baseline_pairs = _result_pairs(baseline.get("results", []))
    candidate_pairs = _result_pairs(candidate.get("results", []))

    baseline_failed = {key for key, value in baseline_pairs.items() if not value["passed"]}
    candidate_failed = {key for key, value in candidate_pairs.items() if not value["passed"]}

    return {
        "baseline": str(Path(baseline_dir)),
        "candidate": str(Path(candidate_dir)),
        "delta": {
            "pass_rate": candidate_summary.get("pass_rate", 0) - baseline_summary.get("pass_rate", 0),
            "avg_score": candidate_summary.get("avg_score", 0) - baseline_summary.get("avg_score", 0),
            "latency_p50_ms": candidate_summary.get("latency_ms", {}).get("p50", 0) - baseline_summary.get("latency_ms", {}).get("p50", 0),
            "latency_p95_ms": candidate_summary.get("latency_ms", {}).get("p95", 0) - baseline_summary.get("latency_ms", {}).get("p95", 0),
            "total_tokens": _total_tokens(candidate_summary) - _total_tokens(baseline_summary),
            "by_capability": _group_delta(baseline_summary.get("by_capability", {}), candidate_summary.get("by_capability", {})),
            "by_risk_level": _group_delta(baseline_summary.get("by_risk_level", {}), candidate_summary.get("by_risk_level", {})),
        },
        "newly_failed": sorted(candidate_failed - baseline_failed),
        "newly_passed": sorted(baseline_failed - candidate_failed),
        "agent_version_delta": agent_delta,
        "baseline_summary": baseline_summary,
        "candidate_summary": candidate_summary,
    }


def write_compare_json(path: str | Path, comparison: dict[str, Any]) -> None:
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(comparison, ensure_ascii=False, indent=2), encoding="utf-8")


def write_compare_markdown(path: str | Path, comparison: dict[str, Any]) -> None:
    delta = comparison["delta"]
    lines = [
        "# AgentEval Compare Report",
        "",
        f"- Baseline: `{comparison['baseline']}`",
        f"- Candidate: `{comparison['candidate']}`",
        "",
        "## Delta",
        "",
        "| Metric | Delta |",
        "| --- | ---: |",
        f"| Pass rate | {delta['pass_rate']:.2%} |",
        f"| Avg score | {delta['avg_score']:.2f} |",
        f"| Latency p50 | {delta['latency_p50_ms']:.0f}ms |",
        f"| Latency p95 | {delta['latency_p95_ms']:.0f}ms |",
        f"| Total tokens | {delta['total_tokens']} |",
        "",
        "## Newly Failed",
        "",
    ]
    lines.extend([f"- `{item}`" for item in comparison["newly_failed"]] or ["None"])
    lines.extend(["", "## Newly Passed", ""])
    lines.extend([f"- `{item}`" for item in comparison["newly_passed"]] or ["None"])
    lines.extend(["", "## Capability Delta", ""])
    lines.extend(_group_delta_lines(delta.get("by_capability", {}), "Capability"))
    lines.extend(["", "## Risk Level Delta", ""])
    lines.extend(_group_delta_lines(delta.get("by_risk_level", {}), "Risk level"))
    lines.extend(["", "## Agent Version Delta", ""])
    version_delta_items = comparison.get("agent_version_delta", {}) or {}
    if version_delta_items:
        for key, values in version_delta_items.items():
            lines.append(f"- `{key}`: `{values.get('baseline')}` → `{values.get('candidate')}`")
    else:
        lines.append("None")
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text("\n".join(lines) + "\n", encoding="utf-8")


def write_compare_html(path: str | Path, comparison: dict[str, Any]) -> None:
    delta = comparison["delta"]
    html = [
        "<!doctype html>",
        "<html><head><meta charset='utf-8'><title>AgentEval Compare Report</title>",
        "<style>body{font-family:-apple-system,BlinkMacSystemFont,Segoe UI,sans-serif;margin:2rem;background:#f6f8fa;color:#182230}.panel{background:white;border:1px solid #e4e7ec;border-radius:16px;padding:1rem;margin:1rem 0}.cards{display:grid;grid-template-columns:repeat(5,minmax(0,1fr));gap:1rem}.card{background:white;border:1px solid #e4e7ec;border-radius:16px;padding:1rem}.neg{color:#b42318}.pos{color:#067647}table{border-collapse:collapse;width:100%}th,td{padding:.7rem;border-bottom:1px solid #e4e7ec;text-align:left}th{background:#f9fafb}code{background:#eef2ff;padding:.12rem .35rem;border-radius:6px}@media(max-width:900px){.cards{grid-template-columns:1fr 1fr}}</style>",
        "</head><body>",
        "<h1>AgentEval Compare Report</h1>",
        f"<p>Baseline: <code>{escape(comparison['baseline'])}</code></p>",
        f"<p>Candidate: <code>{escape(comparison['candidate'])}</code></p>",
        "<section class='cards'>",
        _compare_card("Pass rate", f"{delta['pass_rate']:.2%}", delta["pass_rate"]),
        _compare_card("Avg score", f"{delta['avg_score']:.2f}", delta["avg_score"]),
        _compare_card("Latency p50", f"{delta['latency_p50_ms']:.0f}ms", -delta["latency_p50_ms"]),
        _compare_card("Latency p95", f"{delta['latency_p95_ms']:.0f}ms", -delta["latency_p95_ms"]),
        _compare_card("Total tokens", str(delta["total_tokens"]), -delta["total_tokens"]),
        "</section>",
        _list_panel("Newly Failed", comparison["newly_failed"]),
        _list_panel("Newly Passed", comparison["newly_passed"]),
        _group_delta_panel("Capability Delta", delta.get("by_capability", {}), "Capability"),
        _group_delta_panel("Risk Level Delta", delta.get("by_risk_level", {}), "Risk level"),
        _version_delta_panel(comparison.get("agent_version_delta", {}) or {}),
        "</body></html>",
    ]
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text("\n".join(html), encoding="utf-8")


def _compare_card(title: str, value: str, direction: float) -> str:
    cls = "pos" if direction > 0 else "neg" if direction < 0 else ""
    return f"<article class='card'><p>{escape(title)}</p><h2 class='{cls}'>{escape(value)}</h2></article>"


def _list_panel(title: str, items: list[str]) -> str:
    rows = "".join(f"<tr><td><code>{escape(item)}</code></td></tr>" for item in items) or "<tr><td>None</td></tr>"
    return f"<section class='panel'><h2>{escape(title)}</h2><table>{rows}</table></section>"


def _group_delta_lines(delta: dict[str, dict[str, Any]], label: str) -> list[str]:
    if not delta:
        return ["None"]
    lines = [f"| {label} | Results Δ | Pass rate Δ | Avg score Δ |", "| --- | ---: | ---: | ---: |"]
    for key, item in delta.items():
        lines.append(f"| `{key}` | {item.get('results', 0)} | {float(item.get('pass_rate', 0)):.2%} | {float(item.get('avg_score', 0)):.2f} |")
    return lines


def _group_delta_panel(title: str, delta: dict[str, dict[str, Any]], label: str) -> str:
    rows = "".join(
        f"<tr><td><code>{escape(str(key))}</code></td><td>{item.get('results', 0)}</td><td>{float(item.get('pass_rate', 0)):.2%}</td><td>{float(item.get('avg_score', 0)):.2f}</td></tr>"
        for key, item in delta.items()
    ) or "<tr><td colspan='4'>None</td></tr>"
    return f"<section class='panel'><h2>{escape(title)}</h2><table><tr><th>{escape(label)}</th><th>Results Δ</th><th>Pass rate Δ</th><th>Avg score Δ</th></tr>{rows}</table></section>"


def _version_delta_panel(delta: dict[str, dict[str, Any]]) -> str:
    rows = "".join(
        "<tr>"
        f"<td><code>{escape(key)}</code></td>"
        f"<td><code>{escape(str(values.get('baseline')))}</code></td>"
        f"<td><code>{escape(str(values.get('candidate')))}</code></td>"
        "</tr>"
        for key, values in delta.items()
    ) or "<tr><td colspan='3'>None</td></tr>"
    return f"<section class='panel'><h2>Agent Version Delta</h2><table><tr><th>Field</th><th>Baseline</th><th>Candidate</th></tr>{rows}</table></section>"


def _load_report(run_dir: Path) -> dict[str, Any]:
    report_path = run_dir / "report.json"
    if not report_path.exists():
        raise FileNotFoundError(f"report.json not found in {run_dir}")
    return json.loads(report_path.read_text(encoding="utf-8"))


def _load_manifest(run_dir: Path) -> dict[str, Any]:
    manifest_path = run_dir / "manifest.json"
    if not manifest_path.exists():
        return {}
    return json.loads(manifest_path.read_text(encoding="utf-8"))


def _result_pairs(results: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    return {f"{item['case_id']}::{item['evaluator']}": item for item in results}


def _total_tokens(summary: dict[str, Any]) -> int:
    usage = summary.get("usage", {})
    return int(usage.get("total_input_tokens", 0) + usage.get("output_tokens", 0))


def _group_delta(baseline: dict[str, dict[str, Any]], candidate: dict[str, dict[str, Any]]) -> dict[str, dict[str, float | int]]:
    keys = sorted(set(baseline) | set(candidate))
    return {
        key: {
            "results": int(candidate.get(key, {}).get("results", 0)) - int(baseline.get(key, {}).get("results", 0)),
            "pass_rate": float(candidate.get(key, {}).get("pass_rate", 0)) - float(baseline.get(key, {}).get("pass_rate", 0)),
            "avg_score": float(candidate.get(key, {}).get("avg_score", 0)) - float(baseline.get(key, {}).get("avg_score", 0)),
        }
        for key in keys
    }
