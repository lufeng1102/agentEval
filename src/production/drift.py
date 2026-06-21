from __future__ import annotations

from pathlib import Path
from typing import Any

from production.report import write_report_json, write_report_text

from production.coverage import DIMENSIONS, _segment_counts_from_cases, _segment_counts_from_events
from production.ingest import load_production_events
from config import load_dataset


def analyze_production_drift(baseline_path: str | Path, candidate_path: str | Path, dataset_path: str | Path | None = None, min_delta: float = 0.2) -> dict[str, Any]:
    baseline_events = [event.model_dump(mode="json") for event in load_production_events(baseline_path)]
    candidate_events = [event.model_dump(mode="json") for event in load_production_events(candidate_path)]
    baseline_counts = _segment_counts_from_events(baseline_events)
    candidate_counts = _segment_counts_from_events(candidate_events)
    eval_counts = _segment_counts_from_cases([case.model_dump(mode="json") for case in load_dataset(dataset_path).cases]) if dataset_path else None
    drift = _drift_items(baseline_counts, candidate_counts, min_delta)
    eval_gaps = _eval_gaps(candidate_counts, eval_counts) if eval_counts is not None else {}
    return {
        "baseline": str(baseline_path),
        "candidate": str(candidate_path),
        "dataset": str(dataset_path) if dataset_path else None,
        "summary": {
            "baseline_events": len(baseline_events),
            "candidate_events": len(candidate_events),
            "drift_segments": sum(len(items) for items in drift.values()),
            "eval_gap_segments": sum(len(items) for items in eval_gaps.values()),
        },
        "baseline_counts": baseline_counts,
        "candidate_counts": candidate_counts,
        "drift": drift,
        "eval_gaps": eval_gaps,
        "config": {"min_delta": min_delta},
    }


def write_drift_json(path: str | Path, report: dict[str, Any]) -> None:
    write_report_json(path, report)


def write_drift_markdown(path: str | Path, report: dict[str, Any]) -> None:
    summary = report.get("summary", {}) or {}
    lines = [
        "# AgentEval Production Drift Report",
        "",
        f"- Baseline: `{report.get('baseline')}`",
        f"- Candidate: `{report.get('candidate')}`",
        f"- Dataset: `{report.get('dataset')}`",
        f"- Baseline events: {summary.get('baseline_events', 0)}",
        f"- Candidate events: {summary.get('candidate_events', 0)}",
        f"- Drift segments: {summary.get('drift_segments', 0)}",
        f"- Eval gap segments: {summary.get('eval_gap_segments', 0)}",
        "",
        "## Drift segments",
        "",
    ]
    for dimension, items in (report.get("drift") or {}).items():
        lines.append(f"### {dimension}")
        lines.extend([f"- `{item['segment']}`: baseline={item['baseline_share']:.2%}, candidate={item['candidate_share']:.2%}, delta={item['delta']:.2%}" for item in items] or ["- None"])
        lines.append("")
    lines.extend(["## Candidate segments missing from eval dataset", ""])
    for dimension, items in (report.get("eval_gaps") or {}).items():
        lines.append(f"### {dimension}")
        lines.extend([f"- `{item['segment']}`: candidate_count={item['candidate_count']}" for item in items] or ["- None"])
        lines.append("")
    write_report_text(path, lines)


def _drift_items(baseline_counts: dict[str, dict[str, int]], candidate_counts: dict[str, dict[str, int]], min_delta: float) -> dict[str, list[dict[str, Any]]]:
    result = {}
    for dimension in DIMENSIONS:
        baseline_total = sum(baseline_counts.get(dimension, {}).values())
        candidate_total = sum(candidate_counts.get(dimension, {}).values())
        items = []
        for segment in sorted(set(baseline_counts.get(dimension, {})) | set(candidate_counts.get(dimension, {}))):
            base_share = baseline_counts.get(dimension, {}).get(segment, 0) / baseline_total if baseline_total else 0
            cand_share = candidate_counts.get(dimension, {}).get(segment, 0) / candidate_total if candidate_total else 0
            delta = cand_share - base_share
            if abs(delta) >= min_delta:
                items.append({"segment": segment, "baseline_share": base_share, "candidate_share": cand_share, "delta": delta})
        result[dimension] = items
    return result


def _eval_gaps(candidate_counts: dict[str, dict[str, int]], eval_counts: dict[str, dict[str, int]]) -> dict[str, list[dict[str, Any]]]:
    return {
        dimension: [{"segment": segment, "candidate_count": count, "eval_count": 0} for segment, count in sorted(candidate_counts.get(dimension, {}).items()) if not eval_counts.get(dimension, {}).get(segment)]
        for dimension in DIMENSIONS
    }
