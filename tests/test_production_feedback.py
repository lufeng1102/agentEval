import json

from production.feedback import ingest_feedback, join_feedback, load_user_feedback
from production.ingest import load_production_events


def test_feedback_join_by_event_id_and_session_id(tmp_path):
    events_path = tmp_path / "events.jsonl"
    events_path.write_text("\n".join([json.dumps({"event_id": "e1", "session_id": "s1", "input": "a"}), json.dumps({"event_id": "e2", "session_id": "s2", "input": "b"})]) + "\n", encoding="utf-8")
    feedback_path = tmp_path / "feedback.jsonl"
    feedback_path.write_text("\n".join([json.dumps({"feedback_id": "f1", "event_id": "e1", "rating": -1}), json.dumps({"feedback_id": "f2", "session_id": "s2", "sentiment": "negative"})]) + "\n", encoding="utf-8")

    joined = join_feedback(load_production_events(events_path), load_user_feedback(feedback_path))

    assert sum(len(record.feedback) for record in joined if record.matched) == 2


def test_ingest_feedback_counts_negative_and_unmatched(tmp_path):
    events_path = tmp_path / "events.jsonl"
    events_path.write_text(json.dumps({"event_id": "e1", "session_id": "s1", "input": "a"}) + "\n", encoding="utf-8")
    feedback_path = tmp_path / "feedback.jsonl"
    feedback_path.write_text("\n".join([json.dumps({"feedback_id": "f1", "event_id": "e1", "rating": -1, "category": "incorrect"}), json.dumps({"feedback_id": "f2", "event_id": "missing", "rating": 1})]) + "\n", encoding="utf-8")

    report = ingest_feedback(events_path, feedback_path)

    assert report["summary"]["feedback"] == 2
    assert report["summary"]["negative_feedback"] == 1
    assert report["summary"]["unmatched_feedback"] == 1
