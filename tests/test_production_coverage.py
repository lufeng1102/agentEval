import json

from production.coverage import analyze_production_coverage


def test_production_coverage_finds_uncovered_segments(tmp_path):
    production = tmp_path / "production.json"
    production.write_text(
        json.dumps(
            {
                "events": [
                    {"event_id": "e1", "input": "refund", "tags": ["refund"], "metadata": {"capability": "refunds", "risk_level": "high", "channel": "chat"}},
                    {"event_id": "e2", "input": "cancel", "tags": ["subscription"], "metadata": {"capability": "subscription", "risk_level": "medium", "channel": "chat"}},
                ]
            }
        ),
        encoding="utf-8",
    )
    dataset = tmp_path / "dataset.yaml"
    dataset.write_text("cases:\n  - id: c1\n    input: refund\n    tags: [refund]\n    metadata:\n      capability: refunds\n      risk_level: high\n", encoding="utf-8")

    report = analyze_production_coverage(production, dataset_path=dataset)

    assert report["summary"]["production_events"] == 2
    assert {item["segment"] for item in report["uncovered"]["tag"]} == {"subscription"}
    assert {item["segment"] for item in report["uncovered"]["capability"]} == {"subscription"}
