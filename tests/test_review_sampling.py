from review.sampling import sample_review_items
from tests.review_helpers import write_run


def test_review_sampling_selects_failures_high_risk_judge_and_environment(tmp_path):
    run_dir = write_run(tmp_path / "run")

    report = sample_review_items(run_dir, strategies=["failures", "high-risk", "judge", "environment"], limit=None)

    assert report["summary"]["items"] == 1
    item = report["items"][0]
    assert item["case_id"] == "c_fail"
    assert item["priority"] == "critical"
    assert set(item["strategies"]) == {"failures", "high-risk", "judge", "environment"}
    assert item["environment"]["summary"]["command_failures"] == 1


def test_review_sampling_random_is_deterministic_and_limited(tmp_path):
    run_dir = write_run(tmp_path / "run")

    report = sample_review_items(run_dir, strategies=["random"], limit=1)

    assert len(report["items"]) == 1
    assert report["items"][0]["case_id"] == "c_fail"
    assert report["items"][0]["review_id"].startswith("rev_")

def test_active_sampling_prioritizes_uncertain_and_high_risk_cases(tmp_path):
    run_dir = write_run(tmp_path / "run")

    report = sample_review_items(run_dir, strategies=["active"], active_threshold=1.0, active_margin=0.05)

    assert report["summary"]["items"] == 2
    fail_item = report["items"][0]
    assert fail_item["case_id"] == "c_fail"
    assert "active" in fail_item["strategies"]
    assert fail_item["metadata"]["review"]["active_score"] > 0
    assert "critical risk" in fail_item["metadata"]["review"]["active_reasons"]
    pass_item = next(item for item in report["items"] if item["case_id"] == "c_pass")
    assert "near active threshold" in pass_item["metadata"]["review"]["active_reasons"]
