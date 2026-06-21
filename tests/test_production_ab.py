import json
from pathlib import Path

from production.ab import analyze_ab_test, write_ab_test_json, write_ab_test_markdown


def test_analyze_ab_test_compares_variants(tmp_path: Path) -> None:
    events = tmp_path / "events.jsonl"
    rows = [
        {"event_id": "a1", "input": "q", "variant": "control", "task_success": True, "latency_ms": 100},
        {"event_id": "a2", "input": "q", "variant": "control", "task_success": True, "latency_ms": 120},
        {"event_id": "b1", "input": "q", "variant": "candidate", "task_success": False, "errors": ["boom"], "latency_ms": 200},
    ]
    events.write_text("\n".join(json.dumps(row) for row in rows) + "\n", encoding="utf-8")
    feedback = tmp_path / "feedback.jsonl"
    feedback.write_text(json.dumps({"feedback_id": "f1", "event_id": "b1", "rating": -1}) + "\n", encoding="utf-8")

    report = analyze_ab_test(events, feedback, baseline_variant="control")

    assert report["summary"]["variants"] == 2
    assert report["variants"]["candidate"]["error_rate"] == 1.0
    assert report["comparisons"]["candidate"]["task_success_rate_delta"] == -1.0


def test_analyze_ab_test_warns_when_requested_baseline_is_missing(tmp_path: Path) -> None:
    events = tmp_path / "events.jsonl"
    events.write_text(json.dumps({"event_id": "a1", "input": "q", "variant": "candidate"}) + "\n", encoding="utf-8")

    report = analyze_ab_test(events, baseline_variant="control")

    assert report["warnings"] == ["baseline variant not found: control"]


    report = {"events": "events", "feedback": None, "experiment_id": None, "baseline_variant": "a", "summary": {"variants": 0}, "variants": {}, "comparisons": {}}

    write_ab_test_json(tmp_path / "ab.json", report)
    write_ab_test_markdown(tmp_path / "ab.md", report)

    assert json.loads((tmp_path / "ab.json").read_text(encoding="utf-8"))["baseline_variant"] == "a"
    assert "Production A/B Report" in (tmp_path / "ab.md").read_text(encoding="utf-8")
