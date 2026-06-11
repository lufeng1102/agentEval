from __future__ import annotations

import json
import re
from collections import defaultdict
from datetime import date, datetime
from pathlib import Path
from typing import Any

from config import load_dataset
from evolution.artifacts import load_run_artifacts
from production.coverage import analyze_production_coverage

SEVERITY_ORDER = {"low": 1, "medium": 2, "high": 3, "critical": 4}
HIGH_RISK = {"high", "critical"}


def analyze_suite_health(
    dataset_path: str | Path,
    *,
    runs_path: str | Path | None = None,
    production_path: str | Path | None = None,
    human_review_path: str | Path | None = None,
    stale_days: int = 90,
    saturation_pass_rate: float = 0.98,
    duplicate_fields: list[str] | None = None,
) -> dict[str, Any]:
    dataset = load_dataset(dataset_path)
    cases = [case.model_dump(mode="json") for case in dataset.cases]
    dataset_metadata = dataset.metadata or {}
    human_review = _load_human_review(human_review_path)
    reviewed_cases = _reviewed_cases(human_review)
    issues: list[dict[str, Any]] = []

    issues.extend(_static_issues(cases, dataset_metadata, reviewed_cases, Path(dataset_path), stale_days))
    issues.extend(_duplicate_issues(cases, duplicate_fields or ["input", "tags", "capability"]))

    run_health = _run_health(runs_path, cases, saturation_pass_rate) if runs_path else None
    if run_health:
        issues.extend(run_health.get("issues", []))

    production_coverage = analyze_production_coverage(production_path, dataset_path=dataset_path) if production_path else None
    if production_coverage:
        issues.extend(_production_issues(production_coverage))

    recommendations = _recommendations(issues, production_coverage, human_review)
    summary = _summary(cases, issues, run_health, production_coverage)
    return {
        "dataset": str(dataset_path),
        "metadata": dataset_metadata,
        "summary": summary,
        "issues": sorted(issues, key=lambda item: (-SEVERITY_ORDER.get(item.get("severity", "low"), 0), item.get("category", ""), item.get("case_id") or "")),
        "recommendations": recommendations,
        "run_health": run_health,
        "production_coverage": production_coverage,
        "human_review": human_review,
        "config": {"stale_days": stale_days, "saturation_pass_rate": saturation_pass_rate, "duplicate_fields": duplicate_fields or ["input", "tags", "capability"]},
    }


def write_suite_health_json(path: str | Path, report: dict[str, Any]) -> None:
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")


def write_suite_health_markdown(path: str | Path, report: dict[str, Any]) -> None:
    summary = report.get("summary", {})
    lines = [
        "# AgentEval Suite Health Report",
        "",
        f"- Dataset: `{report.get('dataset')}`",
        f"- Cases: {summary.get('cases', 0)}",
        f"- Issues: {summary.get('issues', 0)} (critical={summary.get('critical', 0)}, high={summary.get('high', 0)}, medium={summary.get('medium', 0)}, low={summary.get('low', 0)})",
        "",
        "## Recommendations",
        "",
    ]
    lines.extend([f"- {item}" for item in report.get("recommendations", [])] or ["None"])
    lines.extend([
        "",
        "## Issues",
        "",
        "| Severity | Category | Case | Title | Recommendation |",
        "| --- | --- | --- | --- | --- |",
    ])
    for issue in report.get("issues", []) or []:
        lines.append(f"| {issue.get('severity')} | {issue.get('category')} | `{issue.get('case_id') or ''}` | {issue.get('title')} | {str(issue.get('recommendation', '')).replace('|', '/')} |")
    if not report.get("issues"):
        lines.append("| none |  |  | No suite health issues found. |  |")

    run_health = report.get("run_health") or {}
    if run_health:
        run_summary = run_health.get("summary", {})
        lines.extend([
            "",
            "## Run Health",
            "",
            f"- Runs analyzed: {run_summary.get('runs', 0)}",
            f"- Cases with history: {run_summary.get('cases_with_history', 0)}",
            f"- Saturated cases: {run_summary.get('saturated_cases', 0)}",
            f"- Flaky/history-unstable cases: {run_summary.get('flaky_cases', 0)}",
        ])

    coverage = report.get("production_coverage") or {}
    if coverage:
        cov_summary = coverage.get("summary", {})
        lines.extend([
            "",
            "## Production Coverage",
            "",
            f"- Production events: {cov_summary.get('production_events', 0)}",
            f"- Uncovered segments: {cov_summary.get('uncovered_segments', 0)}",
            f"- Underrepresented segments: {cov_summary.get('underrepresented_segments', 0)}",
        ])

    human = report.get("human_review") or {}
    if human:
        human_summary = human.get("summary", {})
        lines.extend([
            "",
            "## Human Review",
            "",
            f"- Labeled: {human_summary.get('labeled', 0)}",
            f"- Missing labels: {human_summary.get('missing_labels', 0)}",
            f"- Mismatches: {human_summary.get('mismatches', 0)}",
        ])

    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _static_issues(cases: list[dict[str, Any]], dataset_metadata: dict[str, Any], reviewed_cases: set[str], dataset_path: Path, stale_days: int) -> list[dict[str, Any]]:
    issues = []
    dataset_owner = dataset_metadata.get("owner")
    implicit_sources = [str(source) for source in dataset_metadata.get("sources", []) or []]
    dataset_source = dataset_metadata.get("source") or [source for source in implicit_sources if Path(source) != dataset_path]
    for case in cases:
        case_id = str(case.get("id"))
        metadata = case.get("metadata") or {}
        tags = set(case.get("tags") or [])
        risk = str(metadata.get("risk_level") or "")
        if not (metadata.get("owner") or dataset_owner):
            issues.append(_issue("medium", "metadata", case_id, "Case is missing owner metadata", {"metadata": metadata}, "Add metadata.owner or dataset metadata.owner."))
        if not (metadata.get("source") or metadata.get("sources") or dataset_source):
            issues.append(_issue("medium", "metadata", case_id, "Case is missing source metadata", {"metadata": metadata}, "Add metadata.source, metadata.sources, or dataset metadata.sources."))
        if not case.get("expected") and not case.get("rubric"):
            issues.append(_issue("high", "spec", case_id, "Case has neither expected assertions nor rubric", {}, "Add deterministic expected fields or a rubric so success is reviewable."))
        if not metadata.get("capability"):
            issues.append(_issue("low", "coverage_metadata", case_id, "Case is missing capability metadata", {}, "Add metadata.capability for coverage and release analysis."))
        if not metadata.get("risk_level"):
            issues.append(_issue("low", "coverage_metadata", case_id, "Case is missing risk_level metadata", {}, "Add metadata.risk_level for risk-aware reporting."))
        if risk in HIGH_RISK:
            review_issue = _review_evidence_issue(case_id, metadata, reviewed_cases, stale_days)
            if review_issue:
                issues.append(review_issue)
        regression = metadata.get("regression") or {}
        if ("regression" in tags or regression) and not regression.get("status"):
            issues.append(_issue("medium", "regression", case_id, "Regression case is missing regression status", {}, "Set metadata.regression.status to active, fixed, flaky, ignored, or needs_review."))
    return issues

def _review_evidence_issue(case_id: str, metadata: dict[str, Any], reviewed_cases: set[str], stale_days: int) -> dict[str, Any] | None:
    if case_id in reviewed_cases or metadata.get("review_status"):
        return None
    reviewed_at = metadata.get("last_reviewed_at")
    if not reviewed_at:
        return _issue("high", "human_review", case_id, "High-risk case has no human review evidence", {}, "Add metadata.review_status/last_reviewed_at or include the case in human review artifacts.")
    parsed = _parse_review_date(reviewed_at)
    if parsed is None:
        return _issue("high", "human_review", case_id, "High-risk case has invalid review date", {"last_reviewed_at": reviewed_at}, "Use ISO date format YYYY-MM-DD for metadata.last_reviewed_at.")
    age_days = (date.today() - parsed).days
    if age_days > stale_days:
        return _issue("high", "human_review", case_id, "High-risk case review evidence is stale", {"last_reviewed_at": parsed.isoformat(), "age_days": age_days, "stale_days": stale_days}, "Refresh human review evidence or update metadata.last_reviewed_at after review.")
    return None


def _parse_review_date(value: Any) -> date | None:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if not isinstance(value, str):
        return None
    try:
        return date.fromisoformat(value)
    except ValueError:
        return None

def _duplicate_issues(cases: list[dict[str, Any]], fields: list[str]) -> list[dict[str, Any]]:
    grouped: dict[str, list[str]] = defaultdict(list)
    for case in cases:
        key = _duplicate_key(case, fields)
        grouped[key].append(str(case.get("id")))
    issues = []
    for key, ids in grouped.items():
        if len(ids) > 1:
            issues.append(_issue("medium", "duplicate", ids[0], "Cases have duplicate normalized input/signature", {"case_ids": ids, "signature": key}, "Merge duplicate cases or explain why each variant is distinct."))
    return issues


def _run_health(runs_path: str | Path, cases: list[dict[str, Any]], saturation_pass_rate: float) -> dict[str, Any]:
    run_dirs = _collect_run_dirs(runs_path)
    history: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for run_dir in run_dirs:
        try:
            report = load_run_artifacts(run_dir).report
        except FileNotFoundError:
            continue
        grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for result in report.get("results", []) or []:
            grouped[str(result.get("case_id"))].append(result)
        for case_id, results in grouped.items():
            passed = all(bool(item.get("passed")) for item in results) if results else False
            scores = [float(item.get("score", 0) or 0) for item in results]
            history[case_id].append({"run": str(run_dir), "passed": passed, "avg_score": sum(scores) / len(scores) if scores else 0})
    case_tags = {str(case.get("id")): set(case.get("tags") or []) for case in cases}
    allowed_case_ids = set(case_tags)
    history = {case_id: items for case_id, items in history.items() if case_id in allowed_case_ids}
    issues = []
    saturated = []
    flaky = []
    for case_id, items in history.items():
        pass_count = sum(1 for item in items if item["passed"])
        pass_rate = pass_count / len(items) if items else 0
        if len(items) >= 3 and pass_rate >= saturation_pass_rate and pass_count == len(items):
            saturated.append(case_id)
            issues.append(_issue("low", "saturation", case_id, "Case appears saturated across run history", {"runs": len(items), "pass_rate": pass_rate}, "Consider moving saturated cases to smoke/regression or adding harder capability cases."))
        if pass_count and pass_count < len(items):
            flaky.append(case_id)
            issues.append(_issue("high", "flaky", case_id, "Case has mixed pass/fail outcomes across run history", {"runs": len(items), "pass_rate": pass_rate}, "Investigate agent nondeterminism, task ambiguity, or flaky infrastructure."))
        if "regression" in case_tags.get(case_id, set()) and pass_count == 0:
            issues.append(_issue("high", "regression", case_id, "Regression case has no passing history", {"runs": len(items)}, "Keep active but prioritize repair or mark needs_review if expected behavior is unclear."))
    return {
        "runs": [str(path) for path in run_dirs],
        "summary": {"runs": len(run_dirs), "cases_with_history": len(history), "saturated_cases": len(saturated), "flaky_cases": len(flaky)},
        "cases": {case_id: {"runs": len(items), "pass_rate": sum(1 for item in items if item["passed"]) / len(items), "latest_passed": items[-1]["passed"]} for case_id, items in history.items()},
        "issues": issues,
    }


def _production_issues(coverage: dict[str, Any]) -> list[dict[str, Any]]:
    issues = []
    for dimension, items in (coverage.get("uncovered") or {}).items():
        for item in items:
            severity = "high" if dimension == "risk_level" and item.get("segment") in HIGH_RISK else "medium"
            issues.append(_issue(severity, "production_coverage", None, f"Production {dimension} segment is uncovered", item, "Add eval cases covering this production segment."))
    for dimension, items in (coverage.get("underrepresented") or {}).items():
        for item in items:
            issues.append(_issue("low", "production_coverage", None, f"Production {dimension} segment is underrepresented", item, "Add more eval cases or confirm sampling strategy."))
    return issues


def _load_human_review(path: str | Path | None) -> dict[str, Any] | None:
    if not path:
        return None
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _reviewed_cases(human_review: dict[str, Any] | None) -> set[str]:
    if not human_review:
        return set()
    reviewed = set()
    for record in human_review.get("records", []) or []:
        if record.get("label"):
            item = record.get("item") or {}
            if item.get("case_id"):
                reviewed.add(str(item["case_id"]))
            elif record.get("case_id"):
                reviewed.add(str(record["case_id"]))
    return reviewed


def _recommendations(issues: list[dict[str, Any]], production_coverage: dict[str, Any] | None, human_review: dict[str, Any] | None) -> list[str]:
    categories = {issue.get("category") for issue in issues}
    recommendations = []
    if "metadata" in categories:
        recommendations.append("Add owner/source metadata so eval cases have clear accountability and provenance.")
    if "spec" in categories:
        recommendations.append("Add deterministic expected fields or rubrics for cases that cannot currently be graded clearly.")
    if "flaky" in categories:
        recommendations.append("Investigate flaky cases before using this suite as a promotion gate.")
    if "saturation" in categories:
        recommendations.append("Review saturated cases and add harder capability coverage where scores no longer provide signal.")
    if production_coverage and production_coverage.get("summary", {}).get("uncovered_segments"):
        recommendations.append("Add eval cases for uncovered production segments, prioritizing high-risk traffic.")
    if human_review and human_review.get("summary", {}).get("mismatches"):
        recommendations.append("Review evaluator/judge settings where human labels disagree with automated outcomes.")
    return recommendations or ["No immediate suite health actions detected."]


def _summary(cases: list[dict[str, Any]], issues: list[dict[str, Any]], run_health: dict[str, Any] | None, production_coverage: dict[str, Any] | None) -> dict[str, Any]:
    counts = {severity: sum(1 for issue in issues if issue.get("severity") == severity) for severity in SEVERITY_ORDER}
    return {
        "cases": len(cases),
        "issues": len(issues),
        **counts,
        "missing_owner": sum(1 for issue in issues if issue.get("title") == "Case is missing owner metadata"),
        "missing_source": sum(1 for issue in issues if issue.get("title") == "Case is missing source metadata"),
        "missing_expected_or_rubric": sum(1 for issue in issues if issue.get("category") == "spec"),
        "duplicate_cases": sum(1 for issue in issues if issue.get("category") == "duplicate"),
        "saturated_cases": (run_health or {}).get("summary", {}).get("saturated_cases", 0),
        "flaky_cases": (run_health or {}).get("summary", {}).get("flaky_cases", 0),
        "high_risk_without_review": sum(1 for issue in issues if issue.get("category") == "human_review"),
        "uncovered_production_segments": (production_coverage or {}).get("summary", {}).get("uncovered_segments", 0),
    }


def _collect_run_dirs(path: str | Path) -> list[Path]:
    root = Path(path)
    if (root / "report.json").exists():
        return [root]
    return sorted(item for item in root.iterdir() if item.is_dir() and (item / "report.json").exists()) if root.exists() else []


def _duplicate_key(case: dict[str, Any], fields: list[str]) -> str:
    parts = []
    metadata = case.get("metadata") or {}
    for field in fields:
        if field == "input":
            parts.append(_normalize_text(case.get("input")))
        elif field == "tags":
            parts.append(",".join(sorted(str(tag) for tag in case.get("tags") or [])))
        elif field == "capability":
            parts.append(str(metadata.get("capability") or ""))
        else:
            parts.append(str(case.get(field) or metadata.get(field) or ""))
    return "|".join(parts)


def _normalize_text(value: Any) -> str:
    if isinstance(value, str):
        text = value
    else:
        text = json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)
    return re.sub(r"\s+", " ", text.strip().lower())


def _issue(severity: str, category: str, case_id: str | None, title: str, evidence: dict[str, Any], recommendation: str) -> dict[str, Any]:
    raw = f"{category}_{case_id or 'suite'}_{title}"
    safe = re.sub(r"[^a-zA-Z0-9]+", "_", raw).strip("_").lower()
    return {"id": f"suite_{safe[:100]}", "severity": severity, "case_id": case_id, "category": category, "title": title, "evidence": evidence, "recommendation": recommendation}
