from pathlib import Path

from rsi.self_modification import review_self_modification
from tests.rsi_helpers import write_json, write_run


def test_self_modification_review_scores_safe_change(tmp_path: Path) -> None:
    baseline = write_run(tmp_path / "baseline", pass_rate=0.5)
    candidate = write_run(tmp_path / "candidate", pass_rate=1.0)
    modification = write_json(
        tmp_path / "mod.json",
        {"modified_components": ["prompt"], "rationale": "fix failure", "diff_summary": "add instruction", "rollback_plan": "restore", "expected_impact": {"fixed_failures": ["r1"]}},
    )

    report = review_self_modification(baseline, candidate, modification)

    assert report["passed"] is True
    assert report["score"] >= 0.75
    assert report["pass_rate_delta"] == 0.5


def test_self_modification_review_fails_envelope_violation(tmp_path: Path) -> None:
    baseline = write_run(tmp_path / "baseline", pass_rate=0.5)
    candidate = write_run(tmp_path / "candidate", pass_rate=1.0)
    modification = write_json(tmp_path / "mod.json", {"modified_components": ["safety_policy"], "rationale": "relax", "actions": [{"type": "weaken_safety_policy"}]})
    policy = tmp_path / "policy.yaml"
    policy.write_text("safety_envelope:\n  forbidden_modifications: [safety_policy]\n  forbidden_actions: [weaken_safety_policy]\n", encoding="utf-8")

    report = review_self_modification(baseline, candidate, modification, policy)

    assert report["passed"] is False
    assert report["envelope"]["accepted"] is False
