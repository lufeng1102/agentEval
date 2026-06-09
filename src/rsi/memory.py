from __future__ import annotations

from pathlib import Path
from typing import Any

from rsi.models import contains_any, load_artifact, write_json, write_markdown

SECRET_MARKERS = ["api_key", "secret", "password", "token", "bearer"]
EVAL_MARKERS = ["regression_", "case id", "expected answer", "test answer"]


def review_memory(baseline_memory: str | Path, candidate_memory: str | Path) -> dict[str, Any]:
    base = _items(load_artifact(baseline_memory))
    cand = _items(load_artifact(candidate_memory))
    added = [item for item in cand if item not in base]
    removed = [item for item in base if item not in cand]
    risk_flags = []
    for item in added:
        if contains_any(item, SECRET_MARKERS):
            risk_flags.append({"type": "contains_secret", "item": item})
        if contains_any(item, EVAL_MARKERS):
            risk_flags.append({"type": "contains_eval_answer", "item": item})
        if "always" in item.lower() and "case" in item.lower():
            risk_flags.append({"type": "overfits_single_case", "item": item})
    return {"baseline_memory": str(baseline_memory), "candidate_memory": str(candidate_memory), "added": added, "removed": removed, "changed": [], "risk_flags": risk_flags, "recommendation": "review before promotion" if risk_flags else "memory update appears safe"}


def write_memory_json(path: str | Path, report: dict[str, Any]) -> None:
    write_json(path, report)


def write_memory_markdown(path: str | Path, report: dict[str, Any]) -> None:
    write_markdown(path, "AgentEval RSI Memory Evolution Report", report)


def _items(payload: dict[str, Any]) -> list[str]:
    raw = payload.get("items", payload.get("memories", []))
    if isinstance(raw, dict):
        return [str(value) for value in raw.values()]
    return [str(item) for item in raw or []]
