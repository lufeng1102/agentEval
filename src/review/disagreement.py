from __future__ import annotations

from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

from review.labels import load_human_labels, load_review_queue
from review.models import HumanLabel, ReviewItem, automated_summary


def analyze_disagreements(queue_path: str | Path, label_paths: list[str | Path]) -> dict[str, Any]:
    queue = load_review_queue(queue_path)
    labels = []
    for path in label_paths:
        for label in load_human_labels(path):
            labels.append((str(path), label))
    items_by_key = {_item_key(item): item for item in queue}
    labels_by_key: dict[str, list[tuple[str, HumanLabel]]] = defaultdict(list)
    for source, label in labels:
        labels_by_key[_label_key(label)].append((source, label))

    duplicate_items = []
    reviewer_agreements = []
    needs_adjudication = []
    auto_disagreements = []
    coverage_by_reviewer = Counter()
    false_passes = 0
    false_fails = 0
    by_tag: Counter[str] = Counter()
    by_capability: Counter[str] = Counter()
    by_risk_level: Counter[str] = Counter()
    by_failure_owner: Counter[str] = Counter()
    by_recommended_action: Counter[str] = Counter()

    for key, entries in labels_by_key.items():
        item = items_by_key.get(key)
        if not item:
            continue
        label_payloads = [_label_payload(source, label) for source, label in entries]
        for _source, label in entries:
            coverage_by_reviewer[label.reviewer or "unknown"] += 1
        human_pass_values = {label.human_passed for _source, label in entries}
        human_scores = [label.human_score for _source, label in entries]
        reviewer_disagreement = len(human_pass_values) > 1 or (max(human_scores) - min(human_scores) > 0.25 if human_scores else False)
        if len(entries) > 1:
            duplicate = {
                "review_id": item.review_id,
                "case_id": item.case_id,
                "repeat_index": item.repeat_index,
                "reviewer_count": len(entries),
                "agreement": not reviewer_disagreement,
                "labels": label_payloads,
            }
            duplicate_items.append(duplicate)
            reviewer_agreements.append(not reviewer_disagreement)
        if reviewer_disagreement or any((label.adjudication_status or label.label_status) not in {"adjudicated", "approved"} for _source, label in entries):
            needs_adjudication.append({"review_id": item.review_id, "case_id": item.case_id, "repeat_index": item.repeat_index, "reason": "reviewer disagreement" if reviewer_disagreement else "label not adjudicated", "labels": label_payloads})

        automated_passed, automated_score = automated_summary(item.results)
        for _source, label in entries:
            if automated_passed is not None and automated_passed != label.human_passed:
                mismatch = "false_pass" if automated_passed and not label.human_passed else "false_fail"
                false_passes += 1 if mismatch == "false_pass" else 0
                false_fails += 1 if mismatch == "false_fail" else 0
                auto_disagreements.append(
                    {
                        "review_id": item.review_id,
                        "case_id": item.case_id,
                        "repeat_index": item.repeat_index,
                        "mismatch": mismatch,
                        "automated_passed": automated_passed,
                        "automated_score": automated_score,
                        "human_passed": label.human_passed,
                        "human_score": label.human_score,
                        "human_reason": label.human_reason,
                        "reviewer": label.reviewer,
                        "failure_owner": label.failure_owner,
                        "recommended_action": label.recommended_action,
                        "tags": item.tags,
                        "capability": item.metadata.get("capability"),
                        "risk_level": item.metadata.get("risk_level"),
                    }
                )
                for tag in item.tags:
                    by_tag[str(tag)] += 1
                if item.metadata.get("capability"):
                    by_capability[str(item.metadata.get("capability"))] += 1
                if item.metadata.get("risk_level"):
                    by_risk_level[str(item.metadata.get("risk_level"))] += 1
            by_failure_owner[label.failure_owner] += 1
            by_recommended_action[label.recommended_action or "none"] += 1

    auto_disagreements.sort(key=lambda row: (_risk_rank(row.get("risk_level")), abs(float(row.get("automated_score") or 0) - float(row.get("human_score") or 0))), reverse=True)
    agreement_rate = sum(1 for item in reviewer_agreements if item) / len(reviewer_agreements) if reviewer_agreements else 1.0
    return {
        "queue_path": str(queue_path),
        "label_paths": [str(path) for path in label_paths],
        "summary": {
            "queue_items": len(queue),
            "labels": len(labels),
            "labeled_items": len(labels_by_key),
            "duplicate_labeled_items": len(duplicate_items),
            "reviewer_agreement_rate": agreement_rate,
            "needs_adjudication": len(needs_adjudication),
            "false_passes": false_passes,
            "false_fails": false_fails,
            "automated_human_disagreements": len(auto_disagreements),
        },
        "coverage_by_reviewer": dict(coverage_by_reviewer),
        "by_tag": dict(by_tag),
        "by_capability": dict(by_capability),
        "by_risk_level": dict(by_risk_level),
        "by_failure_owner": dict(by_failure_owner),
        "by_recommended_action": dict(by_recommended_action),
        "duplicate_items": duplicate_items,
        "needs_adjudication_items": needs_adjudication,
        "top_disagreements": auto_disagreements[:20],
    }


def _item_key(item: ReviewItem) -> str:
    return item.review_id or f"{item.case_id}::{item.repeat_index}"


def _label_key(label: HumanLabel) -> str:
    return label.review_id or f"{label.case_id}::{label.repeat_index}"


def _label_payload(source: str, label: HumanLabel) -> dict[str, Any]:
    payload = label.model_dump(mode="json")
    payload["source"] = source
    return payload


def _risk_rank(value: Any) -> int:
    return {"critical": 4, "high": 3, "medium": 2, "low": 1}.get(str(value).lower(), 0)
