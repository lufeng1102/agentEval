from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def build_leaderboard(baseline_name: str, candidate_results: list[dict[str, Any]]) -> dict[str, Any]:
    candidates = []
    for item in candidate_results:
        summary = item.get("summary", {}) or {}
        decision = item.get("decision", {}) or {}
        usage = summary.get("usage", {}) or {}
        candidates.append(
            {
                "id": item.get("id"),
                "run_dir": item.get("run_dir"),
                "pass_rate": float(summary.get("pass_rate", 0) or 0),
                "avg_score": float(summary.get("avg_score", 0) or 0),
                "high_risk_pass_rate": float(summary.get("by_risk_level", {}).get("high", {}).get("pass_rate", 0) or 0),
                "cost_or_tokens": float(usage.get("total_cost_usd") or usage.get("estimated_cost_usd") or int(usage.get("total_input_tokens", 0)) + int(usage.get("output_tokens", 0))),
                "latency_p95_ms": float(summary.get("latency_ms", {}).get("p95", 0) or 0),
                "decision": decision.get("status"),
                "risk_score": int(decision.get("risk_score", 0) or 0),
            }
        )
    ranked = sorted(candidates, key=lambda item: (-item["pass_rate"], -item["avg_score"], item["risk_score"], item["cost_or_tokens"]))
    return {
        "baseline": baseline_name,
        "candidates": ranked,
        "best": {
            "overall": _best(ranked, key=lambda item: (item["decision"] == "accepted", item["pass_rate"], item["avg_score"], -item["risk_score"])),
            "quality": _best(ranked, key=lambda item: (item["pass_rate"], item["avg_score"])),
            "cost": _best(ranked, key=lambda item: (-item["cost_or_tokens"], item["pass_rate"])),
            "high_risk": _best(ranked, key=lambda item: (item["high_risk_pass_rate"], item["pass_rate"])),
        },
    }


def write_leaderboard_json(path: str | Path, report: dict[str, Any]) -> None:
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")


def write_leaderboard_markdown(path: str | Path, report: dict[str, Any]) -> None:
    lines = ["# AgentEval Candidate Leaderboard", "", f"- Baseline: `{report.get('baseline')}`", "", "| Candidate | Pass rate | Avg score | High-risk pass rate | Cost/tokens | Latency p95 | Decision | Risk |", "| --- | ---: | ---: | ---: | ---: | ---: | --- | ---: |"]
    for item in report.get("candidates", []) or []:
        lines.append(f"| `{item['id']}` | {item['pass_rate']:.2%} | {item['avg_score']:.2f} | {item['high_risk_pass_rate']:.2%} | {item['cost_or_tokens']:.0f} | {item['latency_p95_ms']:.0f} | {item.get('decision') or ''} | {item['risk_score']} |")
    lines.extend(["", "## Best", ""])
    for key, value in (report.get("best") or {}).items():
        lines.append(f"- {key}: `{value}`")
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _best(items: list[dict[str, Any]], key) -> str | None:
    if not items:
        return None
    return max(items, key=key).get("id")
