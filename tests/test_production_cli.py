import json

import yaml
from typer.testing import CliRunner

from cli import app


runner = CliRunner()


def _write_inputs(tmp_path):
    events = tmp_path / "events.jsonl"
    events.write_text("\n".join([json.dumps({"event_id": "e1", "session_id": "s1", "input": "refund", "outcome": {"done": True}, "tags": ["refund"], "metadata": {"capability": "refunds", "risk_level": "high"}}), json.dumps({"event_id": "e2", "session_id": "s2", "input": "cancel", "errors": ["timeout"], "metadata": {"capability": "subscription"}})]) + "\n", encoding="utf-8")
    feedback = tmp_path / "feedback.jsonl"
    feedback.write_text(json.dumps({"feedback_id": "f1", "event_id": "e2", "rating": -1, "sentiment": "negative", "category": "tool_error", "comment": "failed", "user_reported_failure": True}) + "\n", encoding="utf-8")
    dataset = tmp_path / "dataset.yaml"
    dataset.write_text("cases:\n  - id: c1\n    input: refund\n    tags: [refund]\n    metadata:\n      capability: refunds\n", encoding="utf-8")
    return events, feedback, dataset


def test_production_cli_flow(tmp_path):
    events, feedback, dataset = _write_inputs(tmp_path)

    ingest = runner.invoke(app, ["production-ingest", "--events", str(events), "--out", str(tmp_path / "production.json"), "--format", "json", "--format", "markdown"])
    assert ingest.exit_code == 0, ingest.output
    assert (tmp_path / "production.json").exists()
    assert (tmp_path / "production.md").exists()

    feedback_result = runner.invoke(app, ["feedback-ingest", "--events", str(events), "--feedback", str(feedback), "--out", str(tmp_path / "feedback.json"), "--format", "json", "--format", "markdown"])
    assert feedback_result.exit_code == 0, feedback_result.output
    assert (tmp_path / "feedback.json").exists()

    regressions = runner.invoke(app, ["feedback-to-regressions", "--events", str(events), "--feedback", str(feedback), "--out", str(tmp_path / "regressions.yaml")])
    assert regressions.exit_code == 0, regressions.output
    loaded = yaml.safe_load((tmp_path / "regressions.yaml").read_text(encoding="utf-8"))
    assert len(loaded["cases"]) == 1

    coverage = runner.invoke(app, ["production-coverage", "--production", str(tmp_path / "production.json"), "--dataset", str(dataset), "--out", str(tmp_path / "coverage.md"), "--format", "markdown", "--format", "json"])
    assert coverage.exit_code == 0, coverage.output
    assert (tmp_path / "coverage.md").exists()
    assert (tmp_path / "coverage.json").exists()

    ab_events = tmp_path / "ab-events.jsonl"
    ab_events.write_text("\n".join([json.dumps({"event_id": "a1", "input": "q", "variant": "control", "task_success": True}), json.dumps({"event_id": "b1", "input": "q", "variant": "candidate", "errors": ["boom"], "task_success": False})]) + "\n", encoding="utf-8")
    ab = runner.invoke(app, ["ab-test", "--events", str(ab_events), "--baseline-variant", "control", "--out", str(tmp_path / "ab.json"), "--format", "json"])
    assert ab.exit_code == 0, ab.output
    assert json.loads((tmp_path / "ab.json").read_text(encoding="utf-8"))["summary"]["variants"] == 2

    drift = runner.invoke(app, ["production-drift", "--baseline", str(events), "--candidate", str(ab_events), "--dataset", str(dataset), "--out", str(tmp_path / "drift.json"), "--format", "json", "--min-delta", "0.1"])
    assert drift.exit_code == 0, drift.output
    assert "drift_segments" in json.loads((tmp_path / "drift.json").read_text(encoding="utf-8"))["summary"]
