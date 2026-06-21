from __future__ import annotations

from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

from review.models import HumanLabel, HumanReviewRecord, ReviewItem, automated_summary
from runners.trace import read_jsonl


def load_review_queue(path: str | Path) -> list[ReviewItem]:
    file_path = Path(path)
    if file_path.suffix == ".jsonl":
        payloads = read_jsonl(file_path)
    else:
        import json

        data = json.loads(file_path.read_text(encoding="utf-8"))
        payloads = data.get("items", data if isinstance(data, list) else [])
    return [ReviewItem.model_validate(item) for item in payloads]


def load_human_labels(path: str | Path) -> list[HumanLabel]:
    file_path = Path(path)
    if file_path.suffix == ".jsonl":
        payloads = read_jsonl(file_path)
    else:
        import json

        data = json.loads(file_path.read_text(encoding="utf-8"))
        payloads = data.get("labels", data if isinstance(data, list) else [])
    return [HumanLabel.model_validate(item) for item in payloads]


def summarize_human_review(queue_path: str | Path, labels_path: str | Path) -> dict[str, Any]:
    queue = load_review_queue(queue_path)
    labels = load_human_labels(labels_path)
    labels_by_review_id = {label.review_id: label for label in labels if label.review_id}
    labels_by_key = {(label.case_id, label.repeat_index): label for label in labels}
    records: list[HumanReviewRecord] = []
    for item in queue:
        label = labels_by_review_id.get(item.review_id) or labels_by_key.get((item.case_id, item.repeat_index))
        automated_passed, automated_score = automated_summary(item.results)
        mismatch = _mismatch(automated_passed, label.human_passed) if label else None
        records.append(HumanReviewRecord(item=item, label=label, automated_passed=automated_passed, automated_score=automated_score, mismatch=mismatch))

    labeled_records = [record for record in records if record.label is not None]
    false_passes = sum(1 for record in labeled_records if record.mismatch == "false_pass")
    false_fails = sum(1 for record in labeled_records if record.mismatch == "false_fail")
    human_scores = [record.label.human_score for record in labeled_records if record.label]
    return {
        "queue_path": str(queue_path),
        "labels_path": str(labels_path),
        "summary": {
            "queue_items": len(queue),
            "labels": len(labels),
            "labeled": len(labeled_records),
            "missing_labels": len(queue) - len(labeled_records),
            "human_pass_rate": sum(1 for record in labeled_records if record.label and record.label.human_passed) / len(labeled_records) if labeled_records else 0,
            "human_avg_score": sum(human_scores) / len(human_scores) if human_scores else 0,
            "false_passes": false_passes,
            "false_fails": false_fails,
            "mismatches": false_passes + false_fails,
            "valid_alternative_solutions": sum(1 for record in labeled_records if record.label and record.label.valid_alternative_solution),
        },
        "failure_types": dict(Counter(label.human_failure_type or "none" for label in labels if not label.human_passed)),
        "failure_owners": dict(Counter(label.failure_owner for label in labels)),
        "recommended_actions": dict(Counter(label.recommended_action or "none" for label in labels)),
        "adjudication_statuses": dict(Counter(label.adjudication_status or "none" for label in labels)),
        "reviewers": dict(Counter(label.reviewer or "unknown" for label in labels)),
        "by_tag": _group_summary(labeled_records, lambda record: record.item.tags),
        "by_capability": _group_summary(labeled_records, lambda record: [str(record.item.metadata.get("capability"))] if record.item.metadata.get("capability") else []),
        "by_risk_level": _group_summary(labeled_records, lambda record: [str(record.item.metadata.get("risk_level"))] if record.item.metadata.get("risk_level") else []),
        "records": [record.model_dump(mode="json") for record in records],
    }


def _mismatch(automated_passed: bool | None, human_passed: bool) -> str | None:
    if automated_passed is None or automated_passed == human_passed:
        return None
    return "false_pass" if automated_passed and not human_passed else "false_fail"


def _group_summary(records: list[HumanReviewRecord], key_fn) -> dict[str, dict[str, Any]]:
    groups: dict[str, list[HumanReviewRecord]] = defaultdict(list)
    for record in records:
        for key in key_fn(record):
            if key and key != "None":
                groups[key].append(record)
    return {
        key: {
            "records": len(items),
            "human_pass_rate": sum(1 for item in items if item.label and item.label.human_passed) / len(items),
            "human_avg_score": sum(item.label.human_score for item in items if item.label) / len(items),
        }
        for key, items in groups.items()
    }


from review.report import write_human_review_json, write_human_review_markdown  # noqa: E402
