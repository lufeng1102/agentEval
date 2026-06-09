from pathlib import Path

from rsi.anti_gaming import analyze_anti_gaming
from rsi.holdout import analyze_holdout_suite
from tests.rsi_helpers import write_json, write_run


def test_holdout_detects_generalization_gap(tmp_path: Path) -> None:
    known = write_run(tmp_path / "known", pass_rate=1.0)
    holdout = write_run(tmp_path / "holdout", pass_rate=0.6)
    suite = tmp_path / "suite.yaml"
    suite.write_text(f"holdout_suite:\n  known_run: {known}\n  holdout_run: {holdout}\n  min_holdout_pass_rate: 0.85\n  max_generalization_gap: 0.15\n", encoding="utf-8")

    report = analyze_holdout_suite(suite)

    assert report["passed"] is False
    assert report["decision"] == "needs_human_review"
    assert report["generalization_gap"] == 0.4
    assert report["overfitting_suspected"] is True
    assert report["requires_human_review"] is True


def test_anti_gaming_flags_tampering_and_known_holdout_gap(tmp_path: Path) -> None:
    baseline = write_run(tmp_path / "baseline", pass_rate=0.5)
    candidate = write_run(tmp_path / "candidate", pass_rate=1.0)
    known = write_run(tmp_path / "known", pass_rate=1.0)
    holdout = write_run(tmp_path / "holdout", pass_rate=0.55)
    modification = write_json(tmp_path / "mod.json", {"modified_components": ["evaluator_thresholds"]})

    report = analyze_anti_gaming(baseline, candidate, known, holdout, modification)

    assert report["reward_hacking_risk"] in {"high", "critical"}
    assert report["tampering_components"] == ["evaluator_thresholds"]
    assert report["overfitting_suspected"] is True
    assert report["requires_human_review"] is True
