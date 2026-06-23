from __future__ import annotations

from pathlib import Path
from typing import Any

from rsi.models import load_report, write_json, write_markdown


def analyze_frontier(runs_dir: str | Path) -> dict[str, Any]:
    entries = []
    by_capability: dict[str, dict[str, Any]] = {}
    for report_path in sorted(Path(runs_dir).glob("*/report.json")):
        report = load_report(report_path.parent)
        summary = report.get("summary", {})
        for case in report.get("cases", []) or []:
            metadata = case.get("metadata", {}) or {}
            capability = str(metadata.get("capability") or "uncategorized")
            difficulty = int(metadata.get("difficulty") or 1)
            risk = str(metadata.get("risk_level") or "low")
            item = by_capability.setdefault(capability, {"capability": capability, "best_difficulty": 0, "best_safe_difficulty": 0, "latest_pass_rate": 0, "runs": [], "unsafe_expansion": False, "regression": False})
            previous = item["latest_pass_rate"]
            item["best_difficulty"] = max(item["best_difficulty"], difficulty)
            if risk not in {"high", "critical"}:
                item["best_safe_difficulty"] = max(item["best_safe_difficulty"], difficulty)
            item["unsafe_expansion"] = item["unsafe_expansion"] or risk in {"high", "critical"}
            item["regression"] = item["regression"] or (bool(item["runs"]) and float(summary.get("pass_rate", 0) or 0) < previous)
            item["latest_pass_rate"] = float(summary.get("pass_rate", 0) or 0)
            item["runs"].append({"run": report_path.parent.name, "difficulty": difficulty, "risk_level": risk, "pass_rate": summary.get("pass_rate", 0)})
        entries.append({"run": report_path.parent.name, "pass_rate": summary.get("pass_rate", 0), "avg_score": summary.get("avg_score", 0)})
    warnings = [f"unsafe capability expansion: {item['capability']}" for item in by_capability.values() if item["unsafe_expansion"]]
    warnings.extend([f"capability regressed: {item['capability']}" for item in by_capability.values() if item.get("regression")])
    return {"runs_dir": str(runs_dir), "runs": entries, "capabilities": sorted(by_capability.values(), key=lambda item: item["capability"]), "warnings": warnings, "risk_level": "high" if any(item["unsafe_expansion"] for item in by_capability.values()) else "medium" if any(item.get("regression") for item in by_capability.values()) else "low"}


def write_frontier_json(path: str | Path, report: dict[str, Any]) -> None:
    write_json(path, report)


def write_frontier_markdown(path: str | Path, report: dict[str, Any]) -> None:
    write_markdown(path, "AgentEval RSI Capability Frontier Report", report)
