from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import yaml

from evolution.artifacts import load_run_artifacts


DEFAULT_REGRESSION_STATUS = "active"
DEFAULT_REGRESSION_SEVERITY = "medium"


def generate_regression_dataset(run_dir: str | Path, tag: str | None = None, evaluator: str | None = None, failure_type: str | None = None) -> dict[str, Any]:
    artifacts = load_run_artifacts(run_dir)
    cases_by_id = {case.get("id"): case for case in artifacts.report.get("cases", []) if isinstance(case, dict)}
    failures_by_case: dict[str, list[dict[str, Any]]] = {}
    for result in artifacts.report.get("results", []) or []:
        if result.get("passed"):
            continue
        if evaluator and result.get("evaluator") != evaluator:
            continue
        if failure_type and result.get("failure_type") != failure_type:
            continue
        case = cases_by_id.get(result.get("case_id"))
        if not case:
            continue
        if tag and tag not in (case.get("tags") or []):
            continue
        failures_by_case.setdefault(str(result.get("case_id")), []).append(result)

    cases = []
    for case_id, failures in sorted(failures_by_case.items()):
        source = dict(cases_by_id[case_id])
        source["id"] = f"regression_{case_id}"
        tags = list(dict.fromkeys([*(source.get("tags") or []), "regression"]))
        source["tags"] = tags
        metadata = dict(source.get("metadata") or {})
        failed_evaluators = sorted({str(item.get("evaluator")) for item in failures})
        failure_types = sorted({str(item.get("failure_type")) for item in failures if item.get("failure_type")})
        failure_reasons = [str(item.get("failure_reason") or "") for item in failures if item.get("failure_reason")]
        fingerprint = regression_fingerprint(source, failed_evaluators, failure_types, failure_reasons)
        metadata["regression"] = {
            "source_case_id": case_id,
            "source_run": str(run_dir),
            "failed_evaluators": failed_evaluators,
            "failure_types": failure_types,
            "failure_reasons": failure_reasons,
            "fingerprint": fingerprint,
            "status": DEFAULT_REGRESSION_STATUS,
            "severity": _severity_for_failures(failures, source),
            "owner": None,
            "component": metadata.get("capability"),
            "review_status": "needs_review",
            "fixed_in_version": None,
            "ignored_reason": None,
            "first_seen_run": str(run_dir),
            "last_seen_run": str(run_dir),
            "seen_count": 1,
        }
        source["metadata"] = metadata
        cases.append(source)
    return {"metadata": {"generated_from_run": str(run_dir), "generated_from_failures": True}, "cases": cases}


def regression_fingerprint(case: dict[str, Any], failed_evaluators: list[str], failure_types: list[str], failure_reasons: list[str]) -> str:
    payload = {
        "input": case.get("input"),
        "expected": case.get("expected") or {},
        "evaluators": sorted(failed_evaluators),
        "failure_types": sorted(failure_types),
        "failure_reasons": sorted(_normalize_reason(reason) for reason in failure_reasons),
    }
    rendered = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(rendered.encode("utf-8")).hexdigest()


def merge_regression_dataset(existing: dict[str, Any], generated: dict[str, Any], dedupe: bool = True) -> dict[str, Any]:
    merged = {
        "metadata": {**(existing.get("metadata") or {})},
        "cases": [dict(case) for case in existing.get("cases") or [] if isinstance(case, dict)],
    }
    generated_metadata = generated.get("metadata") or {}
    if generated_metadata:
        evolution = dict(merged["metadata"].get("evolution") or {})
        evolution["last_merged_run"] = generated_metadata.get("generated_from_run")
        evolution["generated_from_failures"] = bool(generated_metadata.get("generated_from_failures"))
        merged["metadata"]["evolution"] = evolution

    existing_by_fingerprint = {
        _case_fingerprint(case): case
        for case in merged["cases"]
        if _case_fingerprint(case)
    }
    for case in generated.get("cases") or []:
        if not isinstance(case, dict):
            continue
        fingerprint = _case_fingerprint(case)
        if dedupe and fingerprint and fingerprint in existing_by_fingerprint:
            _update_seen(existing_by_fingerprint[fingerprint], case)
            continue
        new_case = dict(case)
        merged["cases"].append(new_case)
        if fingerprint:
            existing_by_fingerprint[fingerprint] = new_case
    return merged


def append_regression_dataset(path: str | Path, generated: dict[str, Any], dedupe: bool = True) -> dict[str, Any]:
    output = Path(path)
    existing = _load_dataset_object(output) if output.exists() else {"metadata": {}, "cases": []}
    merged = merge_regression_dataset(existing, generated, dedupe=dedupe)
    write_regression_dataset(output, merged)
    return merged


def write_regression_dataset(path: str | Path, dataset: dict[str, Any]) -> None:
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(yaml.safe_dump(dataset, allow_unicode=True, sort_keys=False), encoding="utf-8")


def _load_dataset_object(path: Path) -> dict[str, Any]:
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(data, dict):
        raise ValueError(f"regression dataset must contain an object: {path}")
    data.setdefault("metadata", {})
    data.setdefault("cases", [])
    return data


def _case_fingerprint(case: dict[str, Any]) -> str | None:
    metadata = case.get("metadata") if isinstance(case.get("metadata"), dict) else {}
    regression = metadata.get("regression") if isinstance(metadata.get("regression"), dict) else {}
    fingerprint = regression.get("fingerprint")
    return str(fingerprint) if fingerprint else None


def _update_seen(existing: dict[str, Any], incoming: dict[str, Any]) -> None:
    existing_metadata = existing.setdefault("metadata", {})
    existing_regression = existing_metadata.setdefault("regression", {})
    incoming_metadata = incoming.get("metadata") if isinstance(incoming.get("metadata"), dict) else {}
    incoming_regression = incoming_metadata.get("regression") if isinstance(incoming_metadata.get("regression"), dict) else {}
    existing_regression.setdefault("first_seen_run", incoming_regression.get("first_seen_run") or incoming_regression.get("source_run"))
    existing_regression["last_seen_run"] = incoming_regression.get("last_seen_run") or incoming_regression.get("source_run")
    existing_regression["seen_count"] = int(existing_regression.get("seen_count") or 1) + int(incoming_regression.get("seen_count") or 1)


def _normalize_reason(reason: str) -> str:
    return " ".join(str(reason).lower().split())


def _severity_for_failures(failures: list[dict[str, Any]], case: dict[str, Any]) -> str:
    metadata = case.get("metadata") if isinstance(case.get("metadata"), dict) else {}
    if metadata.get("risk_level") in {"critical", "high"}:
        return "high"
    return DEFAULT_REGRESSION_SEVERITY
