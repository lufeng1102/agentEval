import json

from review.disagreement import analyze_disagreements
from review.report import write_review_queue_jsonl
from review.sampling import sample_review_items
from tests.review_helpers import write_run


def test_disagreement_analysis_finds_reviewer_and_auto_mismatches(tmp_path):
    run_dir = write_run(tmp_path / "run")
    queue_report = sample_review_items(run_dir, strategies=["random"])
    queue_path = tmp_path / "queue.jsonl"
    write_review_queue_jsonl(queue_path, queue_report)
    item = queue_report["items"][0]
    labels_a = tmp_path / "labels-a.jsonl"
    labels_b = tmp_path / "labels-b.jsonl"
    labels_a.write_text(json.dumps({"review_id": item["review_id"], "case_id": item["case_id"], "human_passed": True, "human_score": 0.9, "human_reason": "ok", "reviewer": "a", "label_status": "submitted"}) + "\n", encoding="utf-8")
    labels_b.write_text(json.dumps({"review_id": item["review_id"], "case_id": item["case_id"], "human_passed": False, "human_score": 0.1, "human_reason": "bad", "reviewer": "b", "failure_owner": "agent", "recommended_action": "add_regression"}) + "\n", encoding="utf-8")

    report = analyze_disagreements(queue_path, [labels_a, labels_b])

    assert report["summary"]["duplicate_labeled_items"] == 1
    assert report["summary"]["needs_adjudication"] == 1
    assert report["coverage_by_reviewer"] == {"a": 1, "b": 1}
    assert report["summary"]["automated_human_disagreements"] >= 1
