from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import yaml

from evolution.artifacts import load_run_artifacts
from evolution.regressions import write_regression_dataset

VALID_STATUSES = {"active", "fixed", "flaky", "ignored", "needs_review"}


def summarize_regressions(dataset_path: str | Path) -> dict[str, Any]:
    dataset = _load_dataset(dataset_path)
    by_status: dict[str, int] = {}
    by_severity: dict[str, int] = {}
    for case in dataset.get("cases", []) or []:
        regression = _regression(case)
        status = str(regression.get("status") or "active")
        severity = str(regression.get("severity") or "medium")
        by_status[status] = by_status.get(status, 0) + 1
        by_severity[severity] = by_severity.get(severity, 0) + 1
    return {"dataset": str(dataset_path), "total": len(dataset.get("cases", []) or []), "by_status": by_status, "by_severity": by_severity}


def update_regression_status(dataset_path: str | Path, run_dir: str | Path) -> dict[str, Any]:
    dataset = _load_dataset(dataset_path)
    artifacts = load_run_artifacts(run_dir)
    failed = {str(result.get("case_id")) for result in artifacts.report.get("results", []) or [] if not result.get("passed")}
    updated = 0
    for case in dataset.get("cases", []) or []:
        case_id = str(case.get("id"))
        regression = _regression(case)
        if regression.get("status") == "ignored":
            continue
        if case_id in failed:
            regression["status"] = "active"
            regression["last_seen_run"] = str(run_dir)
        else:
            regression["status"] = "fixed"
            regression["fixed_in_version"] = artifacts.manifest.get("agent_version", {}).get("version") or artifacts.manifest.get("run_id") or str(run_dir)
        updated += 1
    write_regression_dataset(dataset_path, dataset)
    summary = summarize_regressions(dataset_path)
    summary["updated"] = updated
    return summary


def mark_regression(dataset_path: str | Path, case_id: str, status: str, reason: str | None = None) -> dict[str, Any]:
    if status not in VALID_STATUSES:
        raise ValueError(f"unsupported regression status: {status}")
    dataset = _load_dataset(dataset_path)
    for case in dataset.get("cases", []) or []:
        if str(case.get("id")) == case_id:
            regression = _regression(case)
            regression["status"] = status
            if status == "ignored":
                regression["ignored_reason"] = reason
            write_regression_dataset(dataset_path, dataset)
            return {"dataset": str(dataset_path), "case_id": case_id, "status": status, "ignored_reason": regression.get("ignored_reason")}
    raise ValueError(f"regression case not found: {case_id}")


def write_regression_status_json(path: str | Path, report: dict[str, Any]) -> None:
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")


def write_regression_status_markdown(path: str | Path, report: dict[str, Any]) -> None:
    lines = ["# AgentEval Regression Status", "", f"- Dataset: `{report.get('dataset')}`", f"- Total: {report.get('total', 0)}", "", "## By Status", ""]
    lines.extend([f"- {status}: {count}" for status, count in sorted((report.get("by_status") or {}).items())] or ["None"])
    lines.extend(["", "## By Severity", ""])
    lines.extend([f"- {severity}: {count}" for severity, count in sorted((report.get("by_severity") or {}).items())] or ["None"])
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _load_dataset(path: str | Path) -> dict[str, Any]:
    payload = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
    if not isinstance(payload, dict):
        raise ValueError(f"regression dataset must contain an object: {path}")
    payload.setdefault("metadata", {})
    payload.setdefault("cases", [])
    return payload


def _regression(case: dict[str, Any]) -> dict[str, Any]:
    metadata = case.setdefault("metadata", {})
    return metadata.setdefault("regression", {})
