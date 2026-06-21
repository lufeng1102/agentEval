import json

from review.labels import load_human_labels, summarize_human_review
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
        {"review_id": queue_report["items"][0]["review_id"], "case_id": "c_fail", "repeat_index": 0, "human_passed": True, "human_score": 0.8, "human_reason": "acceptable", "failure_owner": "grader", "valid_alternative_solution": True, "recommended_action": "relax_grader", "reviewer": "r1"},
        {"case_id": "c_pass", "repeat_index": 0, "human_passed": False, "human_score": 0.1, "human_failure_type": "incorrect", "human_reason": "bad", "failure_owner": "agent", "reviewer": "r2"},
    ]
    labels_path.write_text("\n".join(json.dumps(item) for item in labels) + "\n", encoding="utf-8")

    report = summarize_human_review(queue_path, labels_path)

    assert report["summary"]["labeled"] == 2
    assert report["summary"]["false_fails"] == 1
    assert report["summary"]["false_passes"] == 1
    assert report["failure_types"] == {"incorrect": 1}
    assert report["reviewers"] == {"r1": 1, "r2": 1}
    assert report["failure_owners"] == {"grader": 1, "agent": 1}
    assert report["recommended_actions"] == {"relax_grader": 1, "none": 1}
    assert report["summary"]["valid_alternative_solutions"] == 1


def test_human_label_schema_is_backward_compatible_and_extensible(tmp_path):
    labels_path = tmp_path / "labels.jsonl"
    labels_path.write_text(
        "\n".join(
            [
                json.dumps({"case_id": "legacy", "human_passed": True, "human_score": 1.0, "human_reason": "ok"}),
                json.dumps(
                    {
                        "schema_version": "review_label_v1",
                        "review_id": "rev_1",
                        "case_id": "extended",
                        "human_passed": False,
                        "human_score": 0.2,
                        "human_reason": "wrong",
                        "label_status": "adjudicated",
                        "confidence": 0.9,
                        "reviewer_notes": "needs regression",
                        "golden_candidate": True,
                        "golden_status": "approved",
                        "policy_update": {"require_human_review": True},
                        "regression_update": {"required_facts": ["must cancel"]},
                    }
                ),
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    labels = load_human_labels(labels_path)

    assert labels[0].schema_version == "review_label_v1"
    assert labels[0].golden_candidate is False
    assert labels[1].confidence == 0.9
    assert labels[1].golden_status == "approved"
    assert labels[1].policy_update["require_human_review"] is True
