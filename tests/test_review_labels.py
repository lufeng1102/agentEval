import json

from review.labels import summarize_human_review
from review.report import write_review_queue_jsonl
from review.sampling import sample_review_items
from tests.review_helpers import write_run


def test_review_import_matches_labels_and_counts_mismatches(tmp_path):
    run_dir = write_run(tmp_path / "run")
    queue_report = sample_review_items(run_dir, strategies=["random"], limit=None)
    queue_path = tmp_path / "queue.jsonl"
    write_review_queue_jsonl(queue_path, queue_report)
    labels_path = tmp_path / "labels.jsonl"
    labels = [
        {"review_id": queue_report["items"][0]["review_id"], "case_id": "c_fail", "repeat_index": 0, "human_passed": True, "human_score": 0.8, "human_reason": "acceptable", "reviewer": "r1"},
        {"case_id": "c_pass", "repeat_index": 0, "human_passed": False, "human_score": 0.1, "human_failure_type": "incorrect", "human_reason": "bad", "reviewer": "r2"},
    ]
    labels_path.write_text("\n".join(json.dumps(item) for item in labels) + "\n", encoding="utf-8")

    report = summarize_human_review(queue_path, labels_path)

    assert report["summary"]["labeled"] == 2
    assert report["summary"]["false_fails"] == 1
    assert report["summary"]["false_passes"] == 1
    assert report["failure_types"] == {"incorrect": 1}
    assert report["reviewers"] == {"r1": 1, "r2": 1}
