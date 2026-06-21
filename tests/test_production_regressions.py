import json

import yaml

from production.regressions import production_feedback_to_regressions, recommend_policy_updates, write_production_regressions


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


def test_feedback_to_regressions_uses_reviewed_labels(tmp_path):
    events_path = tmp_path / "events.jsonl"
    events_path.write_text(json.dumps({"event_id": "e1", "session_id": "s1", "input": "cancel", "agent_version": "v1", "tags": ["subscription"], "metadata": {"capability": "subscription", "risk_level": "high"}}) + "\n", encoding="utf-8")
    feedback_path = tmp_path / "feedback.jsonl"
    feedback_path.write_text(json.dumps({"feedback_id": "f1", "event_id": "e1", "rating": -1, "category": "tool_error", "comment": "did not cancel", "user_reported_failure": True}) + "\n", encoding="utf-8")
    labels_path = tmp_path / "labels.jsonl"
    labels_path.write_text(json.dumps({"case_id": "f1", "human_passed": False, "human_score": 0.1, "human_reason": "confirmed", "human_failure_type": "tool_error", "recommended_action": "add_regression", "confidence": 0.95, "regression_update": {"feedback_id": "f1", "required_facts": ["cancel subscription"]}}) + "\n", encoding="utf-8")

    dataset = production_feedback_to_regressions(events_path, feedback_path, review_labels_path=labels_path, require_reviewed=True)

    assert len(dataset["cases"]) == 1
    case = dataset["cases"][0]
    assert case["metadata"]["production"]["review_status"] == "reviewed"
    assert case["metadata"]["production"]["review"]["human_failure_type"] == "tool_error"
    assert case["expected"]["required_facts"] == ["cancel subscription"]


def test_feedback_to_regressions_require_reviewed_skips_unmatched(tmp_path):
    events_path = tmp_path / "events.jsonl"
    events_path.write_text(json.dumps({"event_id": "e1", "session_id": "s1", "input": "cancel"}) + "\n", encoding="utf-8")
    feedback_path = tmp_path / "feedback.jsonl"
    feedback_path.write_text(json.dumps({"feedback_id": "f1", "event_id": "e1", "rating": -1, "user_reported_failure": True}) + "\n", encoding="utf-8")
    labels_path = tmp_path / "labels.jsonl"
    labels_path.write_text(json.dumps({"case_id": "other", "human_passed": False, "human_score": 0.1}) + "\n", encoding="utf-8")

    dataset = production_feedback_to_regressions(events_path, feedback_path, review_labels_path=labels_path, require_reviewed=True)

    assert dataset["cases"] == []
    assert dataset["metadata"]["skipped_unreviewed"] == 1


def test_policy_update_recommendations_use_reviewed_regressions(tmp_path):
    dataset = {
        "cases": [
            {
                "id": "c1",
                "metadata": {
                    "capability": "subscription",
                    "risk_level": "high",
                    "production": {"feedback_id": "f1", "review": {"review_id": "rev1", "recommended_action": "add_gate"}},
                },
            }
        ]
    }

    report = recommend_policy_updates(dataset)

    assert report["summary"]["reviewed_cases"] == 1
    assert any("subscription" in item for item in report["recommendations"])
    assert any("human review" in item for item in report["recommendations"])
