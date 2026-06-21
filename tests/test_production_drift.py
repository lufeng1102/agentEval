import json
from pathlib import Path

from production.drift import analyze_production_drift, write_drift_json, write_drift_markdown


def test_analyze_production_drift_detects_segment_shift_and_eval_gap(tmp_path: Path) -> None:
    baseline = tmp_path / "baseline.jsonl"
    baseline.write_text(
        "\n".join(json.dumps({"event_id": f"b{i}", "input": "refund", "metadata": {"capability": "refunds"}}) for i in range(4)) + "\n",
        encoding="utf-8",
    )
    candidate = tmp_path / "candidate.jsonl"
    candidate.write_text(
        "\n".join(
            [json.dumps({"event_id": "c1", "input": "refund", "metadata": {"capability": "refunds"}})]
            + [json.dumps({"event_id": f"c{i}", "input": "cancel", "metadata": {"capability": "subscription"}}) for i in range(2, 5)]
        )
        + "\n",
        encoding="utf-8",
    )
    dataset = tmp_path / "dataset.yaml"
    dataset.write_text("cases:\n  - id: c1\n    input: refund\n    metadata:\n      capability: refunds\n", encoding="utf-8")

    report = analyze_production_drift(baseline, candidate, dataset_path=dataset, min_delta=0.2)

    assert report["summary"]["drift_segments"] > 0
    assert any(item["segment"] == "subscription" for item in report["eval_gaps"]["capability"])


def test_drift_writers(tmp_path: Path) -> None:
    report = {"baseline": "b", "candidate": "c", "dataset": None, "summary": {"baseline_events": 0, "candidate_events": 0, "drift_segments": 0, "eval_gap_segments": 0}, "drift": {}, "eval_gaps": {}}

    write_drift_json(tmp_path / "drift.json", report)
    write_drift_markdown(tmp_path / "drift.md", report)

    assert json.loads((tmp_path / "drift.json").read_text(encoding="utf-8"))["baseline"] == "b"
    assert "Production Drift Report" in (tmp_path / "drift.md").read_text(encoding="utf-8")
