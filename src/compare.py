from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def compare_runs(baseline_dir: str | Path, candidate_dir: str | Path) -> dict[str, Any]:
    baseline = _load_report(Path(baseline_dir))
    candidate = _load_report(Path(candidate_dir))
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
        },
        "newly_failed": sorted(candidate_failed - baseline_failed),
        "newly_passed": sorted(baseline_failed - candidate_failed),
        "baseline_summary": baseline_summary,
        "candidate_summary": candidate_summary,
    }


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
    Path(path).write_text("\n".join(lines) + "\n", encoding="utf-8")


def _load_report(run_dir: Path) -> dict[str, Any]:
    report_path = run_dir / "report.json"
    if not report_path.exists():
        raise FileNotFoundError(f"report.json not found in {run_dir}")
    return json.loads(report_path.read_text(encoding="utf-8"))


def _result_pairs(results: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    return {f"{item['case_id']}::{item['evaluator']}": item for item in results}


def _total_tokens(summary: dict[str, Any]) -> int:
    usage = summary.get("usage", {})
    return int(usage.get("total_input_tokens", 0) + usage.get("output_tokens", 0))
