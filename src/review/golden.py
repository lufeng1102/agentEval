from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from review.labels import load_human_labels, load_review_queue
from review.models import HumanLabel, ReviewItem
from runners.trace import read_jsonl


def build_golden_labels(
    queue_path: str | Path,
    labels_path: str | Path,
    *,
    allow_submitted: bool = False,
    retire_labels: list[str] | None = None,
) -> dict[str, Any]:
    queue = load_review_queue(queue_path)
    labels = load_human_labels(labels_path)
    items_by_key = {_item_key(item): item for item in queue}
    retired = set(retire_labels or [])
    records = []
    skipped = []
    for label in labels:
        key = _label_key(label)
        item = items_by_key.get(key)
        status = label.adjudication_status or label.label_status
        if key in retired or (label.review_id and label.review_id in retired):
            records.append(_record(item, label, labels_path, status="retired"))
            continue
        if not _is_promotable(label, allow_submitted=allow_submitted):
            skipped.append({"case_id": label.case_id, "review_id": label.review_id, "reason": "label is not adjudicated"})
            continue
        records.append(_record(item, label, labels_path, status=label.golden_status or "approved" if status in {"adjudicated", "approved"} else "candidate"))
    return {
        "queue_path": str(queue_path),
        "labels_path": str(labels_path),
        "summary": {"golden_labels": len(records), "skipped": len(skipped), "retired": sum(1 for record in records if record.get("golden_status") == "retired")},
        "labels": records,
        "skipped": skipped,
    }


def append_golden_labels(path: str | Path, report: dict[str, Any], *, dedupe: bool = True) -> dict[str, Any]:
    output = Path(path)
    existing = []
    if output.exists():
        existing = read_jsonl(output) if output.suffix == ".jsonl" else (json.loads(output.read_text(encoding="utf-8")).get("labels", []))
    labels = [*existing, *(report.get("labels", []) or [])]
    if dedupe:
        by_key = {_golden_key(label): label for label in labels}
        labels = list(by_key.values())
    merged = {**report, "labels": labels, "summary": {**(report.get("summary", {}) or {}), "golden_labels": len(labels)}}
    write_golden_jsonl(output, merged)
    return merged


def golden_labels_to_human_review(queue_path: str | Path, golden_path: str | Path) -> dict[str, Any]:
    queue = load_review_queue(queue_path)
    labels = load_golden_labels(golden_path)
    by_key = {_label_key(label): label for label in labels}
    records = []
    for item in queue:
        label = by_key.get(_item_key(item))
        records.append({"item": item.model_dump(mode="json"), "label": label.model_dump(mode="json") if label else None})
    return {"queue_path": str(queue_path), "labels_path": str(golden_path), "summary": {"queue_items": len(queue), "labels": len(labels), "labeled": sum(1 for record in records if record.get("label"))}, "records": records}


def load_golden_labels(path: str | Path) -> list[HumanLabel]:
    file_path = Path(path)
    if file_path.suffix == ".jsonl":
        payloads = read_jsonl(file_path)
    else:
        data = json.loads(file_path.read_text(encoding="utf-8"))
        payloads = data.get("labels", data if isinstance(data, list) else [])
    normalized = []
    for payload in payloads:
        label_payload = dict(payload.get("label") or payload)
        for key in ["review_id", "case_id", "repeat_index"]:
            if key in payload and key not in label_payload:
                label_payload[key] = payload[key]
        normalized.append(HumanLabel.model_validate(label_payload))
    return normalized


def write_golden_jsonl(path: str | Path, report: dict[str, Any]) -> None:
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", encoding="utf-8") as file:
        for item in report.get("labels", []) or []:
            file.write(json.dumps(item, ensure_ascii=False) + "\n")


def write_golden_json(path: str | Path, report: dict[str, Any]) -> None:
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")


def write_golden_markdown(path: str | Path, report: dict[str, Any]) -> None:
    summary = report.get("summary", {}) or {}
    lines = ["# AgentEval Golden Labels", "", f"- Golden labels: {summary.get('golden_labels', 0)}", f"- Skipped: {summary.get('skipped', 0)}", f"- Retired: {summary.get('retired', 0)}", "", "| Review ID | Case | Status | Reviewer |", "| --- | --- | --- | --- |"]
    for item in report.get("labels", []) or []:
        label = item.get("label", {}) or item
        lines.append(f"| `{item.get('review_id') or label.get('review_id')}` | `{item.get('case_id') or label.get('case_id')}` | `{item.get('golden_status') or label.get('golden_status')}` | `{label.get('reviewer') or 'unknown'}` |")
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _is_promotable(label: HumanLabel, *, allow_submitted: bool) -> bool:
    statuses = {label.adjudication_status, label.label_status, label.golden_status}
    if statuses & {"adjudicated", "approved"}:
        return True
    return allow_submitted and bool(statuses & {"submitted", "candidate"} or label.golden_candidate)


def _record(item: ReviewItem | None, label: HumanLabel, labels_path: str | Path, *, status: str) -> dict[str, Any]:
    label_payload = label.model_dump(mode="json")
    context = item.model_dump(mode="json") if item else {}
    fingerprint = _fingerprint(label_payload)
    return {
        "review_id": label.review_id or context.get("review_id"),
        "case_id": label.case_id,
        "repeat_index": label.repeat_index,
        "run_dir": context.get("run_dir"),
        "tags": context.get("tags", []),
        "capability": (context.get("metadata") or {}).get("capability"),
        "risk_level": (context.get("metadata") or {}).get("risk_level"),
        "golden_status": status,
        "approved_by": label.reviewer,
        "approved_at": label.reviewed_at,
        "source_label_file": str(labels_path),
        "fingerprint": fingerprint,
        "first_seen_at": label.reviewed_at,
        "last_updated_at": label.reviewed_at,
        "label": label_payload,
    }


def _item_key(item: ReviewItem) -> str:
    return item.review_id or f"{item.case_id}::{item.repeat_index}"


def _label_key(label: HumanLabel) -> str:
    return label.review_id or f"{label.case_id}::{label.repeat_index}"


def _golden_key(payload: dict[str, Any]) -> str:
    return str(payload.get("review_id") or f"{payload.get('case_id')}::{payload.get('repeat_index', 0)}::{payload.get('fingerprint')}")


def _fingerprint(payload: dict[str, Any]) -> str:
    return hashlib.sha256(json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()
