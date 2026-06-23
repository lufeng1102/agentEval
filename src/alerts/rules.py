from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

from compare import compare_runs

Severity = Literal["low", "medium", "high", "critical"]
AlertType = Literal["pass_rate_threshold", "avg_score_threshold", "new_failures", "regression"]


class AlertRule(BaseModel):
    id: str
    type: AlertType
    severity: Severity = "high"
    enabled: bool = True
    threshold: float | None = None
    max_drop: float | None = None
    config: dict[str, Any] = Field(default_factory=dict)


class AlertEvent(BaseModel):
    id: str
    rule_id: str
    type: AlertType
    severity: Severity
    run_id: str
    status: str = "open"
    summary: str
    payload: dict[str, Any] = Field(default_factory=dict)
    dedupe_key: str


def evaluate_alert_rules(report: dict[str, Any], rules: list[AlertRule], *, run_id: str = "latest") -> list[AlertEvent]:
    events: list[AlertEvent] = []
    for rule in rules:
        if not rule.enabled:
            continue
        if rule.type in {"pass_rate_threshold", "avg_score_threshold"}:
            events.extend(evaluate_threshold_alerts(report, [rule], run_id=run_id))
    return events


def evaluate_threshold_alerts(report: dict[str, Any], rules: list[AlertRule], *, run_id: str = "latest") -> list[AlertEvent]:
    summary = report.get("summary", {}) or {}
    events = []
    for rule in rules:
        if not rule.enabled:
            continue
        metric = "pass_rate" if rule.type == "pass_rate_threshold" else "avg_score" if rule.type == "avg_score_threshold" else None
        if metric is None or rule.threshold is None:
            continue
        value = float(summary.get(metric, 0) or 0)
        if value < rule.threshold:
            events.append(
                AlertEvent(
                    id=f"alert_{run_id}_{rule.id}",
                    rule_id=rule.id,
                    type=rule.type,
                    severity=rule.severity,
                    run_id=run_id,
                    summary=f"{metric} {value:.2%} is below threshold {rule.threshold:.2%}" if metric == "pass_rate" else f"{metric} {value:.2f} is below threshold {rule.threshold:.2f}",
                    payload={"metric": metric, "value": value, "threshold": rule.threshold, "run_id": run_id},
                    dedupe_key=f"{run_id}:{rule.id}:{metric}",
                )
            )
    return events


def evaluate_regression_alerts(baseline_dir: str, candidate_dir: str, rules: list[AlertRule], *, run_id: str = "candidate") -> list[AlertEvent]:
    comparison = compare_runs(baseline_dir, candidate_dir)
    events = []
    for rule in rules:
        if not rule.enabled:
            continue
        if rule.type == "new_failures" and comparison.get("newly_failed"):
            newly_failed = comparison.get("newly_failed", [])
            events.append(
                AlertEvent(
                    id=f"alert_{run_id}_{rule.id}",
                    rule_id=rule.id,
                    type=rule.type,
                    severity=rule.severity,
                    run_id=run_id,
                    summary=f"{len(newly_failed)} new failures detected",
                    payload={"newly_failed": newly_failed, "comparison": comparison, "run_id": run_id},
                    dedupe_key=f"{run_id}:{rule.id}:new_failures",
                )
            )
        elif rule.type == "regression":
            max_drop = rule.max_drop if rule.max_drop is not None else float(rule.config.get("max_pass_rate_drop", 0) or 0)
            pass_rate_delta = float((comparison.get("delta", {}) or {}).get("pass_rate", 0) or 0)
            if pass_rate_delta < -max_drop:
                events.append(
                    AlertEvent(
                        id=f"alert_{run_id}_{rule.id}",
                        rule_id=rule.id,
                        type=rule.type,
                        severity=rule.severity,
                        run_id=run_id,
                        summary=f"pass_rate dropped by {abs(pass_rate_delta):.2%}, exceeding {max_drop:.2%}",
                        payload={"metric": "pass_rate", "delta": pass_rate_delta, "max_drop": max_drop, "comparison": comparison, "run_id": run_id},
                        dedupe_key=f"{run_id}:{rule.id}:regression",
                    )
                )
    return events
