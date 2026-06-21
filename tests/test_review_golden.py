import json

from review.golden import append_golden_labels, build_golden_labels, load_golden_labels
from review.report import write_review_queue_jsonl
from review.sampling import sample_review_items
from tests.review_helpers import write_run


def test_golden_labels_promote_adjudicated_and_skip_submitted(tmp_path):
    run_dir = write_run(tmp_path / "run")
    queue_report = sample_review_items(run_dir, strategies=["random"])
    queue_path = tmp_path / "queue.jsonl"
    write_review_queue_jsonl(queue_path, queue_report)
    first, second = queue_report["items"]
    labels_path = tmp_path / "labels.jsonl"
    labels_path.write_text(
        "\n".join(
            [
                json.dumps({"review_id": first["review_id"], "case_id": first["case_id"], "human_passed": False, "human_score": 0.1, "human_reason": "bad", "adjudication_status": "adjudicated", "reviewer": "lead"}),
                json.dumps({"review_id": second["review_id"], "case_id": second["case_id"], "human_passed": True, "human_score": 1.0, "human_reason": "ok", "label_status": "submitted"}),
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    report = build_golden_labels(queue_path, labels_path)

    assert report["summary"]["golden_labels"] == 1
    assert report["summary"]["skipped"] == 1
    assert report["labels"][0]["golden_status"] == "approved"
    assert report["labels"][0]["approved_by"] == "lead"


def test_append_golden_labels_dedupes_and_loads(tmp_path):
    run_dir = write_run(tmp_path / "run")
    queue_report = sample_review_items(run_dir, strategies=["random"], limit=1)
    queue_path = tmp_path / "queue.jsonl"
    write_review_queue_jsonl(queue_path, queue_report)
    item = queue_report["items"][0]
    labels_path = tmp_path / "labels.jsonl"
    labels_path.write_text(json.dumps({"review_id": item["review_id"], "case_id": item["case_id"], "human_passed": False, "human_score": 0.2, "human_reason": "bad", "adjudication_status": "adjudicated"}) + "\n", encoding="utf-8")
    report = build_golden_labels(queue_path, labels_path)
    out = tmp_path / "golden.jsonl"

    append_golden_labels(out, report, dedupe=True)
    append_golden_labels(out, report, dedupe=True)
    labels = load_golden_labels(out)

    assert len(labels) == 1
    assert labels[0].review_id == item["review_id"]
