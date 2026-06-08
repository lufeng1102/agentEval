from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, Field

from compare import compare_runs


class PromotionPolicy(BaseModel):
    min_pass_rate: float | None = None
    min_avg_score: float | None = None
    max_pass_rate_drop: float | None = None
    max_avg_score_drop: float | None = None
    fail_on_new_failures: bool = False
    fail_on_new_safety_failures: bool = False
    fail_on_new_state_violations: bool = False
    max_cost_increase: float | None = None
    max_latency_p95_increase: float | None = None
    required_tag_pass_rates: dict[str, float] = Field(default_factory=dict)
    required_capability_pass_rates: dict[str, float] = Field(default_factory=dict)
    required_risk_level_pass_rates: dict[str, float] = Field(default_factory=dict)
    required_evaluator_pass_rates: dict[str, float] = Field(default_factory=dict)


class PromotionResult(BaseModel):
    accepted: bool
    reasons: list[str]
    metrics: dict[str, Any]
    baseline: str
    candidate: str


def load_promotion_policy(path: str | Path) -> PromotionPolicy:
    data = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
    return PromotionPolicy.model_validate(data.get("promotion", data))


def evaluate_promotion(baseline: str | Path, candidate: str | Path, policy: PromotionPolicy) -> PromotionResult:
    comparison = compare_runs(baseline, candidate)
    base = comparison["baseline_summary"]
    cand = comparison["candidate_summary"]
    delta = comparison["delta"]
    reasons: list[str] = []
    gate_metrics: dict[str, Any] = {
        "pass_rate": cand.get("pass_rate", 0),
        "avg_score": cand.get("avg_score", 0),
        "pass_rate_delta": delta.get("pass_rate", 0),
        "avg_score_delta": delta.get("avg_score", 0),
        "latency_p95_delta_ms": delta.get("latency_p95_ms", 0),
        "total_tokens_delta": delta.get("total_tokens", 0),
        "newly_failed": comparison.get("newly_failed", []),
        "agent_version_delta": comparison.get("agent_version_delta", {}),
    }
    if policy.min_pass_rate is not None and cand.get("pass_rate", 0) < policy.min_pass_rate:
        reasons.append(f"pass rate {cand.get('pass_rate', 0):.2%} below required {policy.min_pass_rate:.2%}")
    if policy.min_avg_score is not None and cand.get("avg_score", 0) < policy.min_avg_score:
        reasons.append(f"avg score {cand.get('avg_score', 0):.2f} below required {policy.min_avg_score:.2f}")
    if policy.max_pass_rate_drop is not None and delta.get("pass_rate", 0) < -policy.max_pass_rate_drop:
        reasons.append(f"pass rate drop {-delta['pass_rate']:.2%} exceeds max {policy.max_pass_rate_drop:.2%}")
    if policy.max_avg_score_drop is not None and delta.get("avg_score", 0) < -policy.max_avg_score_drop:
        reasons.append(f"avg score drop {-delta['avg_score']:.2f} exceeds max {policy.max_avg_score_drop:.2f}")
    if policy.fail_on_new_failures and comparison.get("newly_failed"):
        reasons.append(f"new failures: {comparison['newly_failed']}")
    if policy.fail_on_new_safety_failures:
        safety = [item for item in comparison.get("newly_failed", []) if "::safety" in item]
        if safety:
            reasons.append(f"new safety failures: {safety}")
    if policy.fail_on_new_state_violations:
        state = [item for item in comparison.get("newly_failed", []) if "::state" in item]
        if state:
            reasons.append(f"new state violations: {state}")
    if policy.max_latency_p95_increase is not None:
        base_latency = base.get("latency_ms", {}).get("p95", 0)
        latency_increase = _relative_increase(base_latency, cand.get("latency_ms", {}).get("p95", 0))
        gate_metrics["latency_p95_increase"] = latency_increase
        if latency_increase is not None and latency_increase > policy.max_latency_p95_increase:
            reasons.append(f"latency p95 increase {latency_increase:.2%} exceeds max {policy.max_latency_p95_increase:.2%}")
    if policy.max_cost_increase is not None:
        base_cost = _summary_cost_or_tokens(base)
        cand_cost = _summary_cost_or_tokens(cand)
        cost_increase = _relative_increase(base_cost, cand_cost)
        gate_metrics["cost_or_token_increase"] = cost_increase
        gate_metrics["baseline_cost_or_tokens"] = base_cost
        gate_metrics["candidate_cost_or_tokens"] = cand_cost
        if cost_increase is not None and cost_increase > policy.max_cost_increase:
            reasons.append(f"cost/token increase {cost_increase:.2%} exceeds max {policy.max_cost_increase:.2%}")
    tag_metrics: dict[str, float] = {}
    for tag, required in policy.required_tag_pass_rates.items():
        actual = cand.get("by_tag", {}).get(tag, {}).get("pass_rate", 0)
        tag_metrics[tag] = actual
        if actual < required:
            reasons.append(f"tag {tag} pass rate {actual:.2%} below required {required:.2%}")
    evaluator_metrics: dict[str, float] = {}
    for evaluator, required in policy.required_evaluator_pass_rates.items():
        actual = cand.get("by_evaluator", {}).get(evaluator, {}).get("pass_rate", 0)
        evaluator_metrics[evaluator] = actual
        if actual < required:
            reasons.append(f"evaluator {evaluator} pass rate {actual:.2%} below required {required:.2%}")
    capability_metrics: dict[str, float] = {}
    for capability, required in policy.required_capability_pass_rates.items():
        actual = cand.get("by_capability", {}).get(capability, {}).get("pass_rate", 0)
        capability_metrics[capability] = actual
        if actual < required:
            reasons.append(f"capability {capability} pass rate {actual:.2%} below required {required:.2%}")
    risk_level_metrics: dict[str, float] = {}
    for risk_level, required in policy.required_risk_level_pass_rates.items():
        actual = cand.get("by_risk_level", {}).get(risk_level, {}).get("pass_rate", 0)
        risk_level_metrics[risk_level] = actual
        if actual < required:
            reasons.append(f"risk level {risk_level} pass rate {actual:.2%} below required {required:.2%}")
    gate_metrics["tag_pass_rates"] = tag_metrics
    gate_metrics["evaluator_pass_rates"] = evaluator_metrics
    gate_metrics["capability_pass_rates"] = capability_metrics
    gate_metrics["risk_level_pass_rates"] = risk_level_metrics
    return PromotionResult(accepted=not reasons, reasons=reasons, metrics={"comparison": comparison, "gates": gate_metrics}, baseline=str(baseline), candidate=str(candidate))


def write_promotion_json(path: str | Path, result: PromotionResult) -> None:
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result.model_dump(mode="json"), ensure_ascii=False, indent=2), encoding="utf-8")


def write_promotion_markdown(path: str | Path, result: PromotionResult) -> None:
    lines = ["# AgentEval Promotion Report", "", f"- Accepted: {result.accepted}", f"- Baseline: `{result.baseline}`", f"- Candidate: `{result.candidate}`", "", "## Reasons", ""]
    lines.extend([f"- {reason}" for reason in result.reasons] or ["None"])
    agent_delta = result.metrics.get("comparison", {}).get("agent_version_delta", {}) or {}
    lines.extend(["", "## Agent Version Delta", ""])
    if agent_delta:
        for key, values in agent_delta.items():
            lines.append(f"- `{key}`: `{values.get('baseline')}` → `{values.get('candidate')}`")
    else:
        lines.append("None")
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _relative_increase(baseline: float | int | None, candidate: float | int | None) -> float | None:
    baseline_value = float(baseline or 0)
    if baseline_value <= 0:
        return None
    return (float(candidate or 0) - baseline_value) / baseline_value


def _summary_cost_or_tokens(summary: dict[str, Any]) -> float:
    cost = summary.get("cost_usd") or summary.get("estimated_cost_usd")
    if cost is not None:
        return float(cost)
    usage = summary.get("usage", {}) or {}
    return float(usage.get("total_cost_usd") or usage.get("estimated_cost_usd") or int(usage.get("total_input_tokens", 0)) + int(usage.get("output_tokens", 0)))
