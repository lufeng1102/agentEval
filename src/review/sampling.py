from __future__ import annotations

import hashlib
from collections import defaultdict
from pathlib import Path
from typing import Any

from evolution.artifacts import load_run_artifacts
from review.models import ReviewItem

SUPPORTED_STRATEGIES = {"failures", "low-score", "high-risk", "safety", "judge", "environment", "random", "active"}
PRIORITY_RANK = {"low": 1, "medium": 2, "high": 3, "critical": 4}


def sample_review_items(
    run_dir: str | Path,
    strategies: list[str] | None = None,
    limit: int | None = None,
    low_score_threshold: float = 0.7,
    include_traces: bool = True,
    active_threshold: float = 0.7,
    active_margin: float = 0.15,
) -> dict[str, Any]:
    selected_strategies = strategies or ["failures", "low-score", "high-risk"]
    unknown = sorted(set(selected_strategies) - SUPPORTED_STRATEGIES)
    if unknown:
        raise ValueError(f"unsupported review sampling strategies: {', '.join(unknown)}")
    artifacts = load_run_artifacts(run_dir)
    cases = {str(case.get("id")): case for case in artifacts.report.get("cases", []) if isinstance(case, dict)}
    traces = {(str(trace.get("case_id")), int(trace.get("repeat_index", 0) or 0)): trace for trace in artifacts.traces if isinstance(trace, dict)}
    results_by_key: dict[tuple[str, int], list[dict[str, Any]]] = defaultdict(list)
    for result in artifacts.report.get("results", []) or []:
        if not isinstance(result, dict):
            continue
        key = (str(result.get("case_id")), int(result.get("repeat_index", 0) or 0))
        results_by_key[key].append(result)

    candidate_keys = sorted(set(results_by_key) | set(traces) | {(case_id, 0) for case_id in cases})
    items: list[ReviewItem] = []
    for case_id, repeat_index in candidate_keys:
        case = cases.get(case_id, {})
        trace = traces.get((case_id, repeat_index), {}) if include_traces else {}
        results = results_by_key.get((case_id, repeat_index), [])
        active_score, active_reasons = _active_signal(case, trace, results, active_threshold, active_margin)
        matched = _matched_strategies(case, trace, results, selected_strategies, low_score_threshold, active_score)
        if not matched:
            continue
        priority = _priority(case, trace, results, matched)
        metadata = dict(case.get("metadata") or {})
        if "active" in matched:
            review_metadata = dict(metadata.get("review") or {})
            review_metadata.update({"active_score": active_score, "active_reasons": active_reasons})
            metadata["review"] = review_metadata
        items.append(
            ReviewItem(
                review_id=_review_id(run_dir, case_id, repeat_index),
                run_dir=str(run_dir),
                case_id=case_id,
                repeat_index=repeat_index,
                priority=priority,
                strategies=matched,
                input=case.get("input"),
                expected=case.get("expected") or {},
                rubric=case.get("rubric"),
                tags=[str(tag) for tag in case.get("tags", []) or []],
                metadata=metadata,
                agent_output=str(trace.get("final_output", "")),
                messages=_truncate_list(trace.get("messages", []) or [], 20),
                tool_calls=_truncate_list(trace.get("tool_calls", []) or [], 50),
                environment=(trace.get("artifacts", {}) or {}).get("environment", {}) if isinstance(trace.get("artifacts", {}), dict) else {},
                results=results,
                suggested_reason=_suggested_reason(results, matched),
            )
        )
    items.sort(key=lambda item: (-PRIORITY_RANK[item.priority], item.case_id, item.repeat_index))
    if limit is not None:
        items = items[: max(0, limit)]
    return {
        "run_dir": str(run_dir),
        "summary": {"items": len(items), "strategies": selected_strategies, "limit": limit, "active_threshold": active_threshold, "active_margin": active_margin},
        "items": [item.model_dump(mode="json") for item in items],
    }


def _matched_strategies(case: dict[str, Any], trace: dict[str, Any], results: list[dict[str, Any]], strategies: list[str], low_score_threshold: float, active_score: float = 0) -> list[str]:
    matched = []
    for strategy in strategies:
        if strategy == "failures" and any(not result.get("passed") for result in results):
            matched.append(strategy)
        elif strategy == "low-score" and any(float(result.get("score", 0) or 0) < low_score_threshold for result in results):
            matched.append(strategy)
        elif strategy == "high-risk" and str((case.get("metadata") or {}).get("risk_level", "")).lower() in {"high", "critical"}:
            matched.append(strategy)
        elif strategy == "safety" and _has_safety_signal(case, results):
            matched.append(strategy)
        elif strategy == "judge" and any(result.get("judgements") or "judge" in str(result.get("evaluator", "")) for result in results):
            matched.append(strategy)
        elif strategy == "environment" and _has_environment_signal(trace, results):
            matched.append(strategy)
        elif strategy == "random":
            matched.append(strategy)
        elif strategy == "active" and active_score > 0:
            matched.append(strategy)
    return matched


def _priority(case: dict[str, Any], trace: dict[str, Any], results: list[dict[str, Any]], matched: list[str]) -> str:
    risk = str((case.get("metadata") or {}).get("risk_level", "")).lower()
    env = (trace.get("artifacts", {}) or {}).get("environment", {}) if isinstance(trace.get("artifacts", {}), dict) else {}
    protected = ((env.get("diff") or {}).get("protected_path_violations") or []) if isinstance(env, dict) else []
    if risk == "critical" or protected or any("safety" in str(result.get("evaluator", "")) and not result.get("passed") for result in results):
        return "critical"
    if risk == "high" or "environment" in matched or any(not result.get("passed") for result in results):
        return "high"
    if "low-score" in matched or "judge" in matched or "active" in matched:
        return "medium"
    return "low"


def _active_signal(case: dict[str, Any], trace: dict[str, Any], results: list[dict[str, Any]], threshold: float, margin: float) -> tuple[float, list[str]]:
    reasons: list[str] = []
    score = 0.0
    risk = str((case.get("metadata") or {}).get("risk_level", "")).lower()
    if risk in {"high", "critical"}:
        score += 3 if risk == "critical" else 2
        reasons.append(f"{risk} risk")
    scores = [float(result.get("score", 0) or 0) for result in results]
    if any(abs(item - threshold) <= margin for item in scores):
        score += 1.5
        reasons.append("near active threshold")
    passed_values = {bool(result.get("passed")) for result in results if "passed" in result}
    if len(passed_values) > 1:
        score += 2
        reasons.append("mixed evaluator pass/fail")
    if any(result.get("judgements") or "judge" in str(result.get("evaluator", "")).lower() for result in results):
        score += 1
        reasons.append("judge evaluator involved")
    if _has_safety_signal(case, results):
        score += 2
        reasons.append("safety signal")
    if _has_environment_signal(trace, results):
        score += 2
        reasons.append("environment signal")
    if trace.get("errors") or any(result.get("failure_type") == "error" for result in results):
        score += 2
        reasons.append("run or trace error")
    return score, reasons


def _has_safety_signal(case: dict[str, Any], results: list[dict[str, Any]]) -> bool:
    tags = {str(tag).lower() for tag in case.get("tags", []) or []}
    if "safety" in tags:
        return True
    return any("safety" in str(result.get("evaluator", "")).lower() or "safety" in str(result.get("failure_type", "")).lower() for result in results)


def _has_environment_signal(trace: dict[str, Any], results: list[dict[str, Any]]) -> bool:
    if any(str(result.get("evaluator")) in {"environment", "tests"} and not result.get("passed") for result in results):
        return True
    env = (trace.get("artifacts", {}) or {}).get("environment", {}) if isinstance(trace.get("artifacts", {}), dict) else {}
    if not isinstance(env, dict):
        return False
    summary = env.get("summary") or {}
    return any(int(summary.get(key, 0) or 0) > 0 for key in ["protected_path_violations", "command_failures", "query_failures", "http_failures"])


def _suggested_reason(results: list[dict[str, Any]], matched: list[str]) -> str | None:
    failures = [str(result.get("failure_reason")) for result in results if not result.get("passed") and result.get("failure_reason")]
    if failures:
        return "; ".join(failures[:3])
    return f"Matched review strategies: {', '.join(matched)}" if matched else None


def _review_id(run_dir: str | Path, case_id: str, repeat_index: int) -> str:
    digest = hashlib.sha1(f"{Path(run_dir)}::{case_id}::{repeat_index}".encode("utf-8")).hexdigest()
    return f"rev_{digest[:16]}"


def _truncate_list(values: list[Any], limit: int) -> list[Any]:
    return values[:limit]
