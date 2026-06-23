from __future__ import annotations

from pathlib import Path
from typing import Any

from rsi.models import generalization_confidence, load_artifact, load_report, report_counts, risk_level, write_json, write_markdown


def analyze_holdout_suite(suite_path: str | Path) -> dict[str, Any]:
    payload = load_artifact(suite_path)
    suite = payload.get("holdout_suite", payload)
    known_run = suite.get("known_run")
    holdout_run = suite.get("holdout_run")
    if not known_run or not holdout_run:
        raise ValueError("holdout suite requires known_run and holdout_run")
    known_report = load_report(known_run)
    holdout_report = load_report(holdout_run)
    known_counts = report_counts(known_run, known_report)
    holdout_counts = report_counts(holdout_run, holdout_report)
    known_rate = float((known_report.get("summary", {}) or {}).get("pass_rate", 0) or 0)
    holdout_rate = float((holdout_report.get("summary", {}) or {}).get("pass_rate", 0) or 0)
    gap = known_rate - holdout_rate
    min_holdout = float(suite.get("min_holdout_pass_rate", 0))
    max_gap = float(suite.get("max_generalization_gap", 1))
    passed = holdout_rate >= min_holdout and gap <= max_gap
    score = 0 if passed else (50 if holdout_rate < min_holdout else 30) + (30 if gap > max_gap else 0)
    overfitting_suspected = gap > max_gap or (known_rate >= 0.9 and holdout_rate < min_holdout)
    public_gain_transferred = holdout_rate >= known_rate - max_gap
    confidence = generalization_confidence(known_counts, holdout_counts, gap)
    return {
        "passed": passed,
        "decision": "accepted" if passed else "needs_human_review",
        "risk_level": risk_level(score),
        "suite": str(suite_path),
        "known_run": str(known_run),
        "holdout_run": str(holdout_run),
        "known_pass_rate": known_rate,
        "holdout_pass_rate": holdout_rate,
        "generalization_gap": gap,
        "known_counts": known_counts,
        "holdout_counts": holdout_counts,
        "report_aggregate_only": bool(suite.get("report_aggregate_only", True)),
        "overfitting_suspected": overfitting_suspected,
        "public_gain_transferred": public_gain_transferred,
        "requires_human_review": not passed or overfitting_suspected or confidence == "low",
        "confidence": confidence,
        "recommended_action": "rerun with larger hidden/canary sample before promotion" if confidence == "low" else "promote only after hidden holdout review" if overfitting_suspected else "holdout checks passed",
    }


def write_holdout_json(path: str | Path, report: dict[str, Any]) -> None:
    write_json(path, report)


def write_holdout_markdown(path: str | Path, report: dict[str, Any]) -> None:
    write_markdown(path, "AgentEval RSI Holdout Report", report)
