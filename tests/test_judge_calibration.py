import json

from review.calibration import calibrate_judges
from review.labels import summarize_human_review
from review.report import write_human_review_json, write_review_queue_jsonl
from review.sampling import sample_review_items
from tests.review_helpers import write_run


def test_judge_calibration_computes_metrics_and_recommendations(tmp_path):
    run_dir = write_run(tmp_path / "run")
    queue_report = sample_review_items(run_dir, strategies=["random"], limit=None)
    queue_path = tmp_path / "queue.jsonl"
    write_review_queue_jsonl(queue_path, queue_report)
    labels_path = tmp_path / "labels.jsonl"
    labels_path.write_text(
        "\n".join(
            json.dumps(item)
            for item in [
                {"case_id": "c_fail", "repeat_index": 0, "human_passed": True, "human_score": 0.8, "human_reason": "ok"},
                {"case_id": "c_pass", "repeat_index": 0, "human_passed": False, "human_score": 0.1, "human_failure_type": "incorrect", "human_reason": "bad"},
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    human_review = summarize_human_review(queue_path, labels_path)
    human_path = tmp_path / "human-review.json"
    write_human_review_json(human_path, human_review)

    report = calibrate_judges(run_dir, human_path)

    assert report["summary"]["labeled_cases"] == 2
    assert report["summary"]["false_passes"] == 1
    assert report["summary"]["false_fails"] == 1
    assert report["by_evaluator"]["rubric_judge"]["judge_results"] == 1
    assert report["top_disagreements"]
    assert report["recommendations"]
