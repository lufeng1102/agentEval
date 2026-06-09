import json

import yaml

from production.regressions import production_feedback_to_regressions, write_production_regressions


def test_feedback_to_regressions_converts_negative_feedback(tmp_path):
    events_path = tmp_path / "events.jsonl"
    events_path.write_text(json.dumps({"event_id": "e1", "session_id": "s1", "input": "cancel", "agent_version": "v1", "tags": ["subscription"], "metadata": {"capability": "subscription", "risk_level": "medium"}}) + "\n", encoding="utf-8")
    feedback_path = tmp_path / "feedback.jsonl"
    feedback_path.write_text(json.dumps({"feedback_id": "f1", "event_id": "e1", "rating": -1, "category": "tool_error", "comment": "did not cancel", "user_reported_failure": True}) + "\n", encoding="utf-8")

    dataset = production_feedback_to_regressions(events_path, feedback_path)

    assert dataset["metadata"]["generated_from_production"] is True
    assert len(dataset["cases"]) == 1
    case = dataset["cases"][0]
    assert case["id"].startswith("production_e1_f1")
    assert "production" in case["tags"]
    assert case["metadata"]["production"]["review_status"] == "needs_review"


def test_write_production_regressions_yaml(tmp_path):
    dataset = {"metadata": {"generated_from_production": True}, "cases": [{"id": "c1", "input": "q"}]}
    out = tmp_path / "regressions.yaml"

    write_production_regressions(out, dataset)

    loaded = yaml.safe_load(out.read_text(encoding="utf-8"))
    assert loaded["cases"][0]["id"] == "c1"
