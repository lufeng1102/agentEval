from __future__ import annotations

import json
from pathlib import Path

from alerts import AlertRule, build_webhook_payload, deliver_webhook, evaluate_alert_rules, evaluate_regression_alerts
from schemas import EvalResult


def report(pass_rate: float = 1.0, avg_score: float = 1.0) -> dict:
    return {"summary": {"pass_rate": pass_rate, "avg_score": avg_score}}


def write_run(path: Path, *, pass_rate: float, passed: bool) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    (path / "manifest.json").write_text("{}", encoding="utf-8")
    result = EvalResult(case_id="c1", evaluator="contains", score=1.0 if passed else 0.0, passed=passed)
    payload = {"summary": {"pass_rate": pass_rate, "avg_score": pass_rate}, "results": [result.model_dump(mode="json")], "cases": [], "runs": []}
    (path / "report.json").write_text(json.dumps(payload), encoding="utf-8")
    return path


def test_pass_rate_threshold_alert() -> None:
    events = evaluate_alert_rules(report(pass_rate=0.7), [AlertRule(id="pass-rate", type="pass_rate_threshold", threshold=0.8)], run_id="run-1")

    assert len(events) == 1
    assert events[0].type == "pass_rate_threshold"
    assert events[0].payload["metric"] == "pass_rate"
    assert events[0].payload["value"] == 0.7
    assert events[0].dedupe_key == "run-1:pass-rate:pass_rate"


def test_avg_score_threshold_alert() -> None:
    events = evaluate_alert_rules(report(avg_score=0.6), [AlertRule(id="avg-score", type="avg_score_threshold", threshold=0.75)], run_id="run-1")

    assert len(events) == 1
    assert events[0].type == "avg_score_threshold"
    assert events[0].payload["metric"] == "avg_score"


def test_disabled_and_passing_rules_do_not_alert() -> None:
    events = evaluate_alert_rules(
        report(pass_rate=0.9),
        [AlertRule(id="disabled", type="pass_rate_threshold", threshold=0.95, enabled=False), AlertRule(id="passing", type="pass_rate_threshold", threshold=0.8)],
        run_id="run-1",
    )

    assert events == []


def test_new_failures_regression_alert(tmp_path: Path) -> None:
    baseline = write_run(tmp_path / "baseline", pass_rate=1.0, passed=True)
    candidate = write_run(tmp_path / "candidate", pass_rate=0.0, passed=False)

    events = evaluate_regression_alerts(str(baseline), str(candidate), [AlertRule(id="new-failures", type="new_failures")], run_id="candidate")

    assert len(events) == 1
    assert events[0].summary == "1 new failures detected"
    assert events[0].payload["newly_failed"] == ["c1::contains"]


def test_pass_rate_drop_regression_alert(tmp_path: Path) -> None:
    baseline = write_run(tmp_path / "baseline", pass_rate=1.0, passed=True)
    candidate = write_run(tmp_path / "candidate", pass_rate=0.7, passed=True)

    events = evaluate_regression_alerts(str(baseline), str(candidate), [AlertRule(id="drop", type="regression", max_drop=0.1)], run_id="candidate")

    assert len(events) == 1
    assert events[0].payload["delta"] == -0.30000000000000004


def test_webhook_payload_includes_links() -> None:
    event = evaluate_alert_rules(report(pass_rate=0.7), [AlertRule(id="pass-rate", type="pass_rate_threshold", threshold=0.8)], run_id="run-1")[0]

    payload = build_webhook_payload(event, dashboard_url="https://example/runs/run-1", artifact_url="https://example/report.json")

    assert payload["run_id"] == "run-1"
    assert payload["severity"] == "high"
    assert payload["rule_id"] == "pass-rate"
    assert payload["dashboard_url"] == "https://example/runs/run-1"
    assert payload["artifact_url"] == "https://example/report.json"


def test_webhook_delivery_retries_until_success() -> None:
    event = evaluate_alert_rules(report(pass_rate=0.7), [AlertRule(id="pass-rate", type="pass_rate_threshold", threshold=0.8)], run_id="run-1")[0]
    attempts = []

    def sender(url: str, payload: dict) -> tuple[int, str]:
        attempts.append(payload)
        return (500, "no") if len(attempts) == 1 else (200, "ok")

    result = deliver_webhook(event, "https://hooks.example", max_attempts=2, sender=sender)

    assert result.succeeded is True
    assert [delivery.status for delivery in result.deliveries] == ["failed", "succeeded"]
    assert len(attempts) == 2


def test_webhook_delivery_records_failure() -> None:
    event = evaluate_alert_rules(report(pass_rate=0.7), [AlertRule(id="pass-rate", type="pass_rate_threshold", threshold=0.8)], run_id="run-1")[0]

    result = deliver_webhook(event, "https://hooks.example", max_attempts=1, sender=lambda url, payload: (500, "no"))

    assert result.succeeded is False
    assert result.deliveries[0].status == "failed"
    assert result.deliveries[0].response_status == 500
