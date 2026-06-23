from pathlib import Path

from promotion import PromotionPolicy
from rsi.decision_explainer import explain_rsi_decision
from rsi.models import combine_status, normalize_status, risk_level
from tests.rsi_helpers import write_json, write_run


def test_rsi_status_normalizes_canary_alias() -> None:
    assert normalize_status("canary") == "canary_only"
    assert combine_status("accepted", "canary") == "canary_only"
    assert combine_status("canary_only", "rejected") == "rejected"
    assert normalize_status(" Canary ") == "canary_only"
    assert risk_level(" CRITICAL ") == "critical"
    assert risk_level("risk: high") == "high"


def test_rsi_decision_accepts_clean_candidate(tmp_path: Path) -> None:
    baseline = write_run(tmp_path / "baseline", pass_rate=0.8)
    candidate = write_run(tmp_path / "candidate", pass_rate=1.0)

    report = explain_rsi_decision(baseline, candidate, PromotionPolicy(min_pass_rate=0.9))

    assert report["status"] == "accepted"
    assert report["release_recommendation"]["full_release"] is True


def test_rsi_decision_rejects_failed_integrity(tmp_path: Path) -> None:
    baseline = write_run(tmp_path / "baseline", pass_rate=1.0)
    candidate = write_run(tmp_path / "candidate", pass_rate=1.0)
    integrity = write_json(tmp_path / "integrity.json", {"passed": False, "risk_level": "high", "violations": [{"type": "missing_artifact"}], "requires_human_review": True})

    report = explain_rsi_decision(baseline, candidate, PromotionPolicy(min_pass_rate=1.0), integrity_report=integrity)

    assert report["status"] == "rejected"
    assert report["risk_level"] in {"high", "critical"}
    assert report["evidence"]


def test_rsi_decision_requires_review_for_high_diff_risk(tmp_path: Path) -> None:
    baseline = write_run(tmp_path / "baseline", pass_rate=1.0)
    candidate = write_run(tmp_path / "candidate", pass_rate=1.0)
    diff_risk = write_json(tmp_path / "diff.json", {"risk_level": " High ", "risk_categories": ["policy_weakening"], "requires_human_review": True})

    report = explain_rsi_decision(baseline, candidate, PromotionPolicy(min_pass_rate=1.0), diff_risk_report=diff_risk)

    assert report["status"] == "needs_human_review"
    assert any(item["component"] == "diff_risk" for item in report["evidence"])
def test_rsi_decision_requires_review_for_holdout_failure(tmp_path: Path) -> None:
    baseline = write_run(tmp_path / "baseline", pass_rate=1.0)
    candidate = write_run(tmp_path / "candidate", pass_rate=1.0)
    holdout = write_json(
        tmp_path / "holdout.json",
        {"passed": False, "decision": "needs_human_review", "risk_level": "medium", "generalization_gap": 0.35, "requires_human_review": True},
    )

    report = explain_rsi_decision(baseline, candidate, PromotionPolicy(min_pass_rate=1.0), holdout_report=holdout)

    assert report["status"] == "needs_human_review"
    assert any(item["component"] == "holdout" for item in report["evidence"])


def test_rsi_decision_uses_canonical_canary_gate_status(tmp_path: Path) -> None:
    baseline = write_run(tmp_path / "baseline", pass_rate=1.0)
    candidate = write_run(tmp_path / "candidate", pass_rate=1.0)
    memory = write_json(tmp_path / "memory.json", {"risk_level": "medium", "risk_flags": [{"type": "missing_provenance"}]})

    report = explain_rsi_decision(baseline, candidate, PromotionPolicy(min_pass_rate=1.0), memory_report=memory)

    assert report["status"] == "canary_only"
    assert report["canary_required"] is True
    assert next(gate for gate in report["gates"] if gate["name"] == "memory")["status"] == "canary_only"

def test_rsi_decision_rejects_critical_anti_gaming(tmp_path: Path) -> None:
    baseline = write_run(tmp_path / "baseline", pass_rate=1.0)
    candidate = write_run(tmp_path / "candidate", pass_rate=1.0)
    anti_gaming = write_json(
        tmp_path / "anti_gaming.json",
        {"reward_hacking_risk": " CRITICAL ", "generalization_gap": 0.45, "tampering_components": ["evaluator"], "requires_human_review": True},
    )

    report = explain_rsi_decision(baseline, candidate, PromotionPolicy(min_pass_rate=1.0), anti_gaming_report=anti_gaming)

    assert report["status"] == "rejected"
    assert any(item["component"] == "anti_gaming" for item in report["evidence"])
