import json
from pathlib import Path

from evolution.failures import cluster_failures, write_failure_clusters_json, write_failure_clusters_markdown


def test_cluster_failures_includes_trace_and_case_evidence(tmp_path: Path) -> None:
    report = {
        "cases": [
            {"id": "c1", "tags": ["safety"]},
            {"id": "c2", "tags": ["tool-use"]},
        ],
        "results": [
            {"case_id": "c1", "evaluator": "safety", "passed": False, "failure_type": "unsafe", "failure_reason": "leaked secret"},
            {"case_id": "c2", "evaluator": "trajectory", "passed": False, "failure_type": None, "failure_reason": "missing weather"},
            {"case_id": "c2", "evaluator": "contains", "passed": True},
        ],
    }
    traces = [
        {"case_id": "c1", "artifacts": {"dynamic": {"stop_reason": "max_turns"}}, "tool_calls": [{"name": "lookup"}]},
        {"case_id": "c2", "tool_calls": [{"name": "weather"}]},
    ]

    clusters = cluster_failures(report, traces)

    assert clusters["total_failures"] == 2
    unsafe = next(item for item in clusters["clusters"] if item["id"] == "unsafe")
    assert unsafe["tags"] == ["safety"]
    assert unsafe["stop_reasons"] == ["max_turns"]
    assert unsafe["tool_names"] == ["lookup"]
    fallback = next(item for item in clusters["clusters"] if item["id"].startswith("trajectory::"))
    assert fallback["cases"] == ["c2"]


def test_failure_cluster_writers_create_outputs(tmp_path: Path) -> None:
    clusters = {"total_failures": 1, "clusters": [{"id": "unsafe", "size": 1, "cases": ["c1"], "evaluators": ["safety"], "failure_types": ["unsafe"], "tags": [], "stop_reasons": [], "tool_names": [], "evidence": [{"case_id": "c1", "evaluator": "safety", "failure_reason": "bad"}]}]}
    json_path = tmp_path / "nested" / "failures.json"
    md_path = tmp_path / "nested" / "failures.md"

    write_failure_clusters_json(json_path, clusters)
    write_failure_clusters_markdown(md_path, clusters)

    assert json.loads(json_path.read_text(encoding="utf-8"))["total_failures"] == 1
    assert "AgentEval Failure Mining Report" in md_path.read_text(encoding="utf-8")
