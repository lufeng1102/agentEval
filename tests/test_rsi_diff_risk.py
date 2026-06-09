from pathlib import Path

from rsi.diff_risk import classify_diff_risk
from tests.rsi_helpers import write_json


def test_diff_risk_allows_traceable_prompt_repair(tmp_path: Path) -> None:
    modification = write_json(
        tmp_path / "mod.json",
        {
            "modified_components": ["prompt"],
            "rationale": "fix missing instruction",
            "diff_summary": "add explicit formatting guidance",
            "rollback_plan": "restore previous prompt",
            "expected_impact": {"fixed_failures": ["r1"]},
        },
    )

    report = classify_diff_risk(modification)

    assert report["risk_level"] == "low"
    assert report["risk_categories"] == []
    assert report["requires_human_review"] is False


def test_diff_risk_flags_eval_tampering_and_policy_weakening(tmp_path: Path) -> None:
    modification = write_json(
        tmp_path / "mod.json",
        {
            "modified_components": ["evaluator_thresholds", "safety_policy"],
            "rationale": "increase pass rate",
            "diff_summary": "Lowered safety threshold and remove failing cases so checks always pass.",
            "actions": [{"type": "weaken_safety_policy"}, {"type": "disable_logging"}],
        },
    )

    report = classify_diff_risk(modification)

    assert report["risk_level"] == "critical"
    assert "eval_tampering" in report["risk_categories"]
    assert "safety_weakening" in report["risk_categories"]
    assert report["requires_human_review"] is True
    assert report["warnings"]
