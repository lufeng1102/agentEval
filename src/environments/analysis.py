from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any

from rsi.models import write_json, write_markdown


def analyze_environment_independence(run_dir: str | Path) -> dict[str, Any]:
    run_path = Path(run_dir)
    records = _read_jsonl(run_path / "environment.jsonl")
    roots = [str(item.get("root", "")) for item in records]
    duplicate_roots = sorted({root for root in roots if roots.count(root) > 1 and root})
    missing_snapshots = [
        _session_id(item)
        for item in records
        if not item.get("before") or not item.get("after") or not item.get("diff") or not item.get("before", {}).get("root_hash")
    ]
    env_root = (run_path / "envs").resolve()
    outside = []
    for item in records:
        root = item.get("root")
        if not root:
            continue
        try:
            Path(root).resolve().relative_to(env_root)
        except ValueError:
            outside.append(_session_id(item))
    protected = []
    for item in records:
        violations = (item.get("diff") or {}).get("protected_path_violations") or []
        if violations:
            protected.append({"session": _session_id(item), "violations": violations})
    warnings = []
    if not records:
        warnings.append("environment.jsonl has no sessions")
    passed = bool(records) and not duplicate_roots and not missing_snapshots and not outside
    return {
        "passed": passed,
        "run": str(run_dir),
        "sessions": len(records),
        "unique_roots": len(set(roots)),
        "missing_snapshots": missing_snapshots,
        "shared_roots": duplicate_roots,
        "outside_run_roots": outside,
        "protected_path_violations": protected,
        "warnings": warnings,
    }


def clean_environment_workspaces(run_dir: str | Path, keep_failures: bool = False, dry_run: bool = True) -> dict[str, Any]:
    run_path = Path(run_dir)
    envs_dir = run_path / "envs"
    failed_cases = _failed_cases(run_path) if keep_failures else set()
    planned_delete = []
    kept = []
    deleted = []
    if envs_dir.exists():
        for case_dir in sorted(item for item in envs_dir.iterdir() if item.is_dir()):
            if case_dir.name in failed_cases:
                kept.append(str(case_dir))
                continue
            planned_delete.append(str(case_dir))
            if not dry_run:
                shutil.rmtree(case_dir)
                deleted.append(str(case_dir))
    return {"run": str(run_dir), "dry_run": dry_run, "keep_failures": keep_failures, "failed_cases": sorted(failed_cases), "planned_delete": planned_delete, "deleted": deleted, "kept": kept}


def write_environment_analysis_json(path: str | Path, report: dict[str, Any]) -> None:
    write_json(path, report)


def write_environment_analysis_markdown(path: str | Path, report: dict[str, Any]) -> None:
    write_markdown(path, "AgentEval Environment Independence Report", report)


def write_environment_cleanup_json(path: str | Path, report: dict[str, Any]) -> None:
    write_json(path, report)


def write_environment_cleanup_markdown(path: str | Path, report: dict[str, Any]) -> None:
    write_markdown(path, "AgentEval Environment Cleanup Report", report)


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def _failed_cases(run_path: Path) -> set[str]:
    report_path = run_path / "report.json"
    if not report_path.exists():
        return set()
    payload = json.loads(report_path.read_text(encoding="utf-8"))
    return {str(item.get("case_id")) for item in payload.get("results", []) if not item.get("passed", True)}


def _session_id(item: dict[str, Any]) -> str:
    return f"{item.get('case_id')}:{item.get('repeat_index')}"
