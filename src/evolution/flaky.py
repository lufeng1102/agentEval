from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path
from typing import Any

from evolution.artifacts import load_run_artifacts
from runners.trace import read_jsonl


def analyze_flaky(run_dir: str | Path) -> dict[str, Any]:
    artifacts = load_run_artifacts(run_dir)
    results = list(artifacts.report.get("results", []) or [])
    if not _has_repeats(results):
        jsonl = read_jsonl(Path(run_dir) / "results.jsonl")
        if jsonl:
            results = jsonl
    case_metadata = {str(case.get("id")): case.get("metadata", {}) or {} for case in artifacts.report.get("cases", []) or [] if isinstance(case, dict)}
    grouped: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for result in results:
        grouped[(str(result.get("case_id")), str(result.get("evaluator")))].append(result)
    flaky_results = []
    for (case_id, evaluator), items in grouped.items():
        if len(items) < 3:
            continue
        pass_count = sum(1 for item in items if item.get("passed"))
        fail_count = len(items) - pass_count
        if pass_count and fail_count:
            scores = [float(item.get("score", 0) or 0) for item in items]
            metadata = case_metadata.get(case_id, {})
            flaky_results.append(
                {
                    "case_id": case_id,
                    "evaluator": evaluator,
                    "repeats": len(items),
                    "passed": pass_count,
                    "failed": fail_count,
                    "pass_rate": pass_count / len(items),
                    "scores": scores,
                    "risk_level": metadata.get("risk_level"),
                    "capability": metadata.get("capability"),
                }
            )
    high_risk = [item for item in flaky_results if item.get("risk_level") in {"high", "critical"}]
    total_pairs = len(grouped)
    return {
        "run": str(run_dir),
        "summary": {
            "flaky_pairs": len(flaky_results),
            "flaky_rate": len(flaky_results) / total_pairs if total_pairs else 0,
            "high_risk_flaky": len(high_risk),
        },
        "flaky_results": sorted(flaky_results, key=lambda item: (item.get("risk_level") != "high", item["case_id"], item["evaluator"])),
    }


def write_flaky_json(path: str | Path, report: dict[str, Any]) -> None:
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")


def write_flaky_markdown(path: str | Path, report: dict[str, Any]) -> None:
    summary = report.get("summary", {})
    lines = [
        "# AgentEval Flaky Report",
        "",
        f"- Run: `{report.get('run')}`",
        f"- Flaky pairs: {summary.get('flaky_pairs', 0)}",
        f"- Flaky rate: {float(summary.get('flaky_rate', 0)):.2%}",
        f"- High-risk flaky pairs: {summary.get('high_risk_flaky', 0)}",
        "",
        "| Case | Evaluator | Repeats | Pass rate | Risk level | Capability |",
        "| --- | --- | ---: | ---: | --- | --- |",
    ]
    for item in report.get("flaky_results", []) or []:
        lines.append(f"| `{item['case_id']}` | `{item['evaluator']}` | {item['repeats']} | {float(item['pass_rate']):.2%} | {item.get('risk_level') or ''} | {item.get('capability') or ''} |")
    if not report.get("flaky_results"):
        lines.append("| None |  | 0 | 0.00% |  |  |")
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _has_repeats(results: list[dict[str, Any]]) -> bool:
    counts: dict[tuple[str, str], int] = defaultdict(int)
    for result in results:
        counts[(str(result.get("case_id")), str(result.get("evaluator")))] += 1
    return any(count >= 2 for count in counts.values())
