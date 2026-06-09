import json
from pathlib import Path

from rsi.integrity import analyze_eval_integrity
from tests.rsi_helpers import write_json, write_run


def _write_complete_run(path: Path) -> Path:
    write_run(path, pass_rate=1.0)
    (path / "manifest.json").write_text(json.dumps({"agent_version": {"prompt": "v1"}}), encoding="utf-8")
    (path / "traces.jsonl").write_text(json.dumps({"case_id": "c1"}) + "\n", encoding="utf-8")
    (path / "results.jsonl").write_text(json.dumps({"case_id": "c1", "evaluator": "contains"}) + "\n", encoding="utf-8")
    return path


def test_integrity_passes_complete_clean_run(tmp_path: Path) -> None:
    candidate = _write_complete_run(tmp_path / "candidate")

    report = analyze_eval_integrity(candidate)

    assert report["passed"] is True
    assert report["risk_level"] == "low"
    assert report["violations"] == []


def test_integrity_fails_missing_artifacts(tmp_path: Path) -> None:
    candidate = write_run(tmp_path / "candidate", pass_rate=1.0)

    report = analyze_eval_integrity(candidate)

    assert report["passed"] is False
    assert any(item["item"] == "manifest.json" for item in report["violations"])
    assert report["requires_human_review"] is True


def test_integrity_flags_protected_component_tampering(tmp_path: Path) -> None:
    candidate = _write_complete_run(tmp_path / "candidate")
    modification = write_json(tmp_path / "mod.json", {"modified_components": ["evaluator"], "actions": [{"type": "modify_evaluator"}]})

    report = analyze_eval_integrity(candidate, modification_path=modification)

    assert report["passed"] is False
    assert report["tampering_components"] == ["evaluator"]
    assert report["tampering_actions"] == ["modify_evaluator"]
def test_integrity_fails_incomplete_results_jsonl(tmp_path: Path) -> None:
    candidate = _write_complete_run(tmp_path / "candidate")
    report_path = candidate / "report.json"
    report = json.loads(report_path.read_text(encoding="utf-8"))
    report["results"].append({"case_id": "c2", "evaluator": "contains", "passed": True, "score": 1})
    report_path.write_text(json.dumps(report), encoding="utf-8")

    integrity = analyze_eval_integrity(candidate)

    assert integrity["passed"] is False
    assert any(item["type"] == "incomplete_results" for item in integrity["violations"])
    assert integrity["artifact_checks"]["results_jsonl_line_count"]["actual"] == 1
