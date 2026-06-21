from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path
from typing import Any

from evolution.artifacts import load_run_artifacts
from evaluators.judge_metrics import JUDGE_METRIC_TYPES


def calibrate_judges(run_dir: str | Path, human_review_path: str | Path) -> dict[str, Any]:
    artifacts = load_run_artifacts(run_dir)
    human_review = json.loads(Path(human_review_path).read_text(encoding="utf-8"))
    result_by_key: dict[tuple[str, int], list[dict[str, Any]]] = defaultdict(list)
    for result in artifacts.report.get("results", []) or []:
        result_by_key[(str(result.get("case_id")), int(result.get("repeat_index", 0) or 0))].append(result)
    rows = []
    for record in human_review.get("records", []) or []:
        label = record.get("label")
        item = record.get("item") or {}
        if not label:
            continue
        key = (str(item.get("case_id") or label.get("case_id")), int(item.get("repeat_index", label.get("repeat_index", 0)) or 0))
        for result in result_by_key.get(key, []):
            rows.append(_row(item, label, result))
    overall = _stats(rows)
    by_evaluator = {key: _stats(items) for key, items in _group(rows, "evaluator").items()}
    by_tag = {key: _stats(items) for key, items in _group_multi(rows, "tags").items()}
    by_capability = {key: _stats(items) for key, items in _group_meta(rows, "capability").items()}
    by_risk_level = {key: _stats(items) for key, items in _group_meta(rows, "risk_level").items()}
    by_failure_owner = {key: _stats(items) for key, items in _group(rows, "failure_owner").items()}
    disagreements = [row for row in rows if row["automated_passed"] != row["human_passed"]]
    disagreements.sort(key=lambda item: (-_risk_rank(item.get("risk_level")), -abs(item.get("score_gap", 0)), item["case_id"], item["evaluator"]))
    return {
        "run_dir": str(run_dir),
        "human_review": str(human_review_path),
        "summary": overall,
        "by_evaluator": by_evaluator,
        "by_tag": by_tag,
        "by_capability": by_capability,
        "by_risk_level": by_risk_level,
        "by_failure_owner": by_failure_owner,
        "confusion_matrix": _confusion_matrix(rows),
        "top_disagreements": disagreements[:20],
        "recommendations": _recommendations(overall, by_evaluator, disagreements),
    }


def _row(item: dict[str, Any], label: dict[str, Any], result: dict[str, Any]) -> dict[str, Any]:
    human_score = float(label.get("human_score", 0) or 0)
    auto_score = float(result.get("score", 0) or 0)
    evaluator = str(result.get("evaluator"))
    return {
        "case_id": str(result.get("case_id")),
        "repeat_index": int(result.get("repeat_index", 0) or 0),
        "evaluator": evaluator,
        "is_judge": bool(result.get("judgements")) or "judge" in evaluator or evaluator in JUDGE_METRIC_TYPES,
        "human_passed": bool(label.get("human_passed")),
        "human_score": human_score,
        "human_failure_type": label.get("human_failure_type"),
        "failure_owner": label.get("failure_owner") or "unclear",
        "valid_alternative_solution": bool(label.get("valid_alternative_solution")),
        "recommended_action": label.get("recommended_action"),
        "human_reason": label.get("human_reason"),
        "automated_passed": bool(result.get("passed")),
        "automated_score": auto_score,
        "automated_failure_type": result.get("failure_type"),
        "score_gap": abs(auto_score - human_score),
        "tags": item.get("tags", []) or [],
        "capability": (item.get("metadata") or {}).get("capability"),
        "risk_level": (item.get("metadata") or {}).get("risk_level"),
    }


def _stats(rows: list[dict[str, Any]]) -> dict[str, Any]:
    total = len(rows)
    if not total:
        return {"cases": 0, "labeled_cases": 0, "agreement_rate": 0, "false_passes": 0, "false_fails": 0, "precision": 0, "recall": 0, "f1": 0, "mean_absolute_score_error": 0, "judge_results": 0}
    tp = sum(1 for row in rows if row["automated_passed"] and row["human_passed"])
    tn = sum(1 for row in rows if not row["automated_passed"] and not row["human_passed"])
    fp = sum(1 for row in rows if row["automated_passed"] and not row["human_passed"])
    fn = sum(1 for row in rows if not row["automated_passed"] and row["human_passed"])
    precision = tp / (tp + fp) if tp + fp else 0
    recall = tp / (tp + fn) if tp + fn else 0
    f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0
    return {
        "cases": total,
        "labeled_cases": total,
        "agreement_rate": (tp + tn) / total,
        "false_passes": fp,
        "false_fails": fn,
        "true_passes": tp,
        "true_fails": tn,
        "precision": precision,
        "recall": recall,
        "f1": f1,
        "mean_absolute_score_error": sum(row["score_gap"] for row in rows) / total,
        "judge_results": sum(1 for row in rows if row.get("is_judge")),
    }


def _group(rows: list[dict[str, Any]], key: str) -> dict[str, list[dict[str, Any]]]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        grouped[str(row.get(key) or "unknown")].append(row)
    return grouped


def _group_multi(rows: list[dict[str, Any]], key: str) -> dict[str, list[dict[str, Any]]]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        for value in row.get(key) or []:
            grouped[str(value)].append(row)
    return grouped


def _group_meta(rows: list[dict[str, Any]], key: str) -> dict[str, list[dict[str, Any]]]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        value = row.get(key)
        if value:
            grouped[str(value)].append(row)
    return grouped


def _confusion_matrix(rows: list[dict[str, Any]]) -> dict[str, int]:
    return {
        "true_pass": sum(1 for row in rows if row["automated_passed"] and row["human_passed"]),
        "true_fail": sum(1 for row in rows if not row["automated_passed"] and not row["human_passed"]),
        "false_pass": sum(1 for row in rows if row["automated_passed"] and not row["human_passed"]),
        "false_fail": sum(1 for row in rows if not row["automated_passed"] and row["human_passed"]),
    }


def _risk_rank(value: Any) -> int:
    return {"critical": 4, "high": 3, "medium": 2, "low": 1}.get(str(value).lower(), 0)


def _recommendations(summary: dict[str, Any], by_evaluator: dict[str, dict[str, Any]], disagreements: list[dict[str, Any]]) -> list[str]:
    recs = []
    if summary.get("false_passes", 0) > 0:
        recs.append("False passes found: tighten thresholds, split broad rubrics, or add deterministic outcome evaluators for these cases.")
    if summary.get("false_fails", 0) > 0:
        recs.append("False fails found: inspect overly strict evaluators and ambiguous expected/rubric fields.")
    if float(summary.get("mean_absolute_score_error", 0) or 0) >= 0.25:
        recs.append("Score error is high: calibrate judge prompts against human labels before using scores as release gates.")
    weak = [name for name, stats in by_evaluator.items() if stats.get("cases", 0) >= 2 and float(stats.get("agreement_rate", 0) or 0) < 0.8]
    if weak:
        recs.append(f"Low-agreement evaluators need review: {', '.join(sorted(weak))}.")
    if any(_risk_rank(item.get("risk_level")) >= 3 for item in disagreements):
        recs.append("High-risk disagreements found: require human review before promotion for matching tags/capabilities.")
    return recs or ["Calibration looks acceptable for the labeled sample; continue periodic human review sampling."]


from review.report import write_calibration_json, write_calibration_markdown  # noqa: E402
