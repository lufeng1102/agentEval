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
