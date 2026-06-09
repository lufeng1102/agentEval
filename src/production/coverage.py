from __future__ import annotations

import json
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

from config import load_dataset
from evolution.artifacts import load_run_artifacts
from production.ingest import load_production_events

DIMENSIONS = ["tag", "capability", "risk_level", "channel", "intent", "locale"]


def analyze_production_coverage(production_path: str | Path, dataset_path: str | Path | None = None, run_path: str | Path | None = None) -> dict[str, Any]:
    events = _load_production_artifact(production_path)
    eval_cases = _load_eval_cases(dataset_path, run_path)
    production_counts = _segment_counts_from_events(events)
    eval_counts = _segment_counts_from_cases(eval_cases)
    uncovered = _uncovered(production_counts, eval_counts)
    underrepresented = _underrepresented(production_counts, eval_counts)
    return {
        "production": str(production_path),
        "dataset": str(dataset_path) if dataset_path else None,
        "run": str(run_path) if run_path else None,
        "summary": {
            "production_events": len(events),
            "eval_cases": len(eval_cases),
            "uncovered_segments": sum(len(items) for items in uncovered.values()),
            "underrepresented_segments": sum(len(items) for items in underrepresented.values()),
        },
        "production_counts": production_counts,
        "eval_counts": eval_counts,
        "uncovered": uncovered,
        "underrepresented": underrepresented,
    }


def _load_production_artifact(path: str | Path) -> list[dict[str, Any]]:
    file_path = Path(path)
    if file_path.suffix == ".jsonl":
        return [event.model_dump(mode="json") for event in load_production_events(file_path)]
    data = json.loads(file_path.read_text(encoding="utf-8"))
    if isinstance(data, dict) and "events" in data:
        return data.get("events") or []
    if isinstance(data, list):
        return data
    return [event.model_dump(mode="json") for event in load_production_events(file_path)]


def _load_eval_cases(dataset_path: str | Path | None, run_path: str | Path | None) -> list[dict[str, Any]]:
    cases: list[dict[str, Any]] = []
    if dataset_path:
        cases.extend([case.model_dump(mode="json") for case in load_dataset(dataset_path).cases])
    if run_path:
        cases.extend(load_run_artifacts(run_path).report.get("cases", []) or [])
    return cases


def _segment_counts_from_events(events: list[dict[str, Any]]) -> dict[str, dict[str, int]]:
    counts: dict[str, Counter] = {dimension: Counter() for dimension in DIMENSIONS}
    for event in events:
        for tag in event.get("tags") or []:
            counts["tag"][str(tag)] += 1
        metadata = event.get("metadata") or {}
        for dimension in ["capability", "risk_level", "channel", "intent", "locale"]:
            if metadata.get(dimension):
                counts[dimension][str(metadata[dimension])] += 1
    return {key: dict(value) for key, value in counts.items()}


def _segment_counts_from_cases(cases: list[dict[str, Any]]) -> dict[str, dict[str, int]]:
    counts: dict[str, Counter] = {dimension: Counter() for dimension in DIMENSIONS}
    for case in cases:
        for tag in case.get("tags") or []:
            counts["tag"][str(tag)] += 1
        metadata = case.get("metadata") or {}
        for dimension in ["capability", "risk_level", "channel", "intent", "locale"]:
            if metadata.get(dimension):
                counts[dimension][str(metadata[dimension])] += 1
    return {key: dict(value) for key, value in counts.items()}


def _uncovered(production_counts: dict[str, dict[str, int]], eval_counts: dict[str, dict[str, int]]) -> dict[str, list[dict[str, Any]]]:
    return {
        dimension: [{"segment": segment, "production_count": count, "eval_count": 0} for segment, count in sorted(values.items()) if not eval_counts.get(dimension, {}).get(segment)]
        for dimension, values in production_counts.items()
    }


def _underrepresented(production_counts: dict[str, dict[str, int]], eval_counts: dict[str, dict[str, int]]) -> dict[str, list[dict[str, Any]]]:
    result = {}
    for dimension, values in production_counts.items():
        items = []
        for segment, prod_count in sorted(values.items()):
            eval_count = eval_counts.get(dimension, {}).get(segment, 0)
            if eval_count and prod_count >= 3 and eval_count < prod_count / 2:
                items.append({"segment": segment, "production_count": prod_count, "eval_count": eval_count})
        result[dimension] = items
    return result
