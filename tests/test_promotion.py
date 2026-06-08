import json
from pathlib import Path

from promotion import PromotionPolicy, PromotionResult, evaluate_promotion, load_promotion_policy, write_promotion_json, write_promotion_markdown


def _write_report(path: Path, *, pass_rate: float, avg_score: float, results: list[dict], latency_p95: float = 100, tokens: int = 100, by_tag: dict | None = None, by_evaluator: dict | None = None, by_capability: dict | None = None, by_risk_level: dict | None = None) -> None:
    path.mkdir(parents=True, exist_ok=True)
    payload = {
        "summary": {
            "pass_rate": pass_rate,
            "avg_score": avg_score,
            "latency_ms": {"p50": latency_p95 / 2, "p95": latency_p95},
            "usage": {"total_input_tokens": tokens, "output_tokens": 0},
            "by_tag": by_tag or {},
            "by_evaluator": by_evaluator or {},
            "by_capability": by_capability or {},
            "by_risk_level": by_risk_level or {},
        },
        "results": results,
    }
    (path / "report.json").write_text(json.dumps(payload), encoding="utf-8")


def test_promotion_accepts_when_gates_pass(tmp_path: Path) -> None:
    baseline = tmp_path / "baseline"
    candidate = tmp_path / "candidate"
    results = [{"case_id": "c1", "evaluator": "contains", "passed": True}]
    _write_report(baseline, pass_rate=1.0, avg_score=1.0, results=results)
    _write_report(candidate, pass_rate=1.0, avg_score=1.0, results=results)

    result = evaluate_promotion(baseline, candidate, PromotionPolicy(min_pass_rate=0.9, fail_on_new_failures=True))

    assert result.accepted is True
    assert result.reasons == []
    assert result.metrics["gates"]["pass_rate"] == 1.0


def test_promotion_rejects_quality_safety_state_latency_and_cost_gates(tmp_path: Path) -> None:
    baseline = tmp_path / "baseline"
    candidate = tmp_path / "candidate"
    _write_report(
        baseline,
        pass_rate=1.0,
        avg_score=1.0,
        latency_p95=100,
        tokens=100,
        results=[{"case_id": "c1", "evaluator": "safety", "passed": True}, {"case_id": "c2", "evaluator": "state", "passed": True}],
    )
    _write_report(
        candidate,
        pass_rate=0.5,
        avg_score=0.5,
        latency_p95=200,
        tokens=200,
        by_tag={"safety": {"pass_rate": 0.5}},
        by_evaluator={"safety": {"pass_rate": 0.5}},
        by_capability={"refund": {"pass_rate": 0.5}},
        by_risk_level={"high": {"pass_rate": 0.5}},
        results=[{"case_id": "c1", "evaluator": "safety", "passed": False}, {"case_id": "c2", "evaluator": "state", "passed": False}],
    )

    result = evaluate_promotion(
        baseline,
        candidate,
        PromotionPolicy(
            min_pass_rate=0.9,
            min_avg_score=0.9,
            max_pass_rate_drop=0.1,
            max_avg_score_drop=0.1,
            fail_on_new_failures=True,
            fail_on_new_safety_failures=True,
            fail_on_new_state_violations=True,
            max_latency_p95_increase=0.5,
            max_cost_increase=0.5,
            required_tag_pass_rates={"safety": 0.9},
            required_evaluator_pass_rates={"safety": 0.9},
            required_capability_pass_rates={"refund": 0.9},
            required_risk_level_pass_rates={"high": 0.9},
        ),
    )

    assert result.accepted is False
    reasons = "\n".join(result.reasons)
    assert "pass rate" in reasons
    assert "new safety failures" in reasons
    assert "new state violations" in reasons
    assert "latency p95 increase" in reasons
    assert "cost/token increase" in reasons
    assert "tag safety" in reasons
    assert "evaluator safety" in reasons
    assert "capability refund" in reasons
    assert "risk level high" in reasons


def test_promotion_policy_loader_and_writers(tmp_path: Path) -> None:
    policy_path = tmp_path / "policy.yaml"
    policy_path.write_text("promotion:\n  min_pass_rate: 0.8\n", encoding="utf-8")
    policy = load_promotion_policy(policy_path)
    promotion_result = PromotionResult(accepted=False, reasons=["no"], metrics={"comparison": {"agent_version_delta": {}}}, baseline="b", candidate="c")
    json_path = tmp_path / "nested" / "promotion.json"
    md_path = tmp_path / "nested" / "promotion.md"
    write_promotion_json(json_path, promotion_result)
    write_promotion_markdown(md_path, promotion_result)

    assert policy.min_pass_rate == 0.8
    assert json.loads(json_path.read_text(encoding="utf-8"))["accepted"] is False
    assert "AgentEval Promotion Report" in md_path.read_text(encoding="utf-8")
