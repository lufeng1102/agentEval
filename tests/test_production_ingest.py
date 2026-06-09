import json

from production.ingest import ingest_production_events, load_production_events


def test_load_production_events_jsonl_and_generate_missing_id(tmp_path):
    path = tmp_path / "events.jsonl"
    path.write_text(json.dumps({"session_id": "s1", "input": "hello", "final_output": "hi", "metadata": {"capability": "chat"}}) + "\n", encoding="utf-8")

    events = load_production_events(path)

    assert len(events) == 1
    assert events[0].event_id.startswith("prod_")
    assert events[0].input == "hello"


def test_ingest_production_events_summarizes_errors_and_segments(tmp_path):
    path = tmp_path / "events.jsonl"
    rows = [
        {"event_id": "e1", "input": "refund", "outcome": {"done": True}, "latency_ms": 10, "tags": ["refund"], "metadata": {"capability": "refunds", "risk_level": "high"}},
        {"event_id": "e2", "input": "cancel", "errors": ["timeout"], "latency_ms": 30, "metadata": {"capability": "subscription"}},
    ]
    path.write_text("\n".join(json.dumps(row) for row in rows) + "\n", encoding="utf-8")

    report = ingest_production_events(path)

    assert report["summary"]["events"] == 2
    assert report["summary"]["errors"] == 1
    assert report["summary"]["outcome_coverage"] == 0.5
    assert report["summary"]["by_capability"] == {"refunds": 1, "subscription": 1}
