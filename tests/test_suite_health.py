import json
from pathlib import Path

from evolution.suite_health import analyze_suite_health, write_suite_health_json, write_suite_health_markdown


def test_suite_health_flags_missing_metadata_spec_and_duplicates(tmp_path: Path) -> None:
    dataset = tmp_path / "dataset.yaml"
    dataset.write_text(
        "cases:\n"
        "  - id: c1\n"
        "    input: refund please\n"
        "    tags: [refund]\n"
        "    metadata:\n"
        "      capability: refunds\n"
        "      risk_level: high\n"
        "  - id: c2\n"
        "    input: refund please\n"
        "    tags: [refund]\n"
        "    expected:\n"
        "      answer: ok\n"
        "    metadata:\n"
        "      capability: refunds\n"
        "      risk_level: high\n",
        encoding="utf-8",
    )

    report = analyze_suite_health(dataset)

    titles = {issue["title"] for issue in report["issues"]}
    assert "Case is missing owner metadata" in titles
    assert "Case is missing source metadata" in titles
    assert "Case has neither expected assertions nor rubric" in titles
    assert "High-risk case has no human review evidence" in titles
    assert "Cases have duplicate normalized input/signature" in titles
    assert report["summary"]["missing_expected_or_rubric"] == 1
    assert report["summary"]["duplicate_cases"] == 1


def test_suite_health_integrates_run_history_saturation_and_flaky(tmp_path: Path) -> None:
    dataset = tmp_path / "dataset.yaml"
    dataset.write_text(
        "metadata:\n  owner: eval-team\n  sources: [seed]\n"
        "cases:\n"
        "  - id: stable\n    input: stable\n    expected:\n      answer: ok\n    tags: [regression]\n    metadata:\n      capability: refunds\n      risk_level: low\n      regression:\n        status: active\n"
        "  - id: flaky\n    input: flaky\n    expected:\n      answer: ok\n    metadata:\n      capability: refunds\n      risk_level: low\n",
        encoding="utf-8",
    )
    runs = tmp_path / "runs"
    for index, flaky_passed in enumerate([True, False, True], start=1):
        run_dir = runs / f"run{index}"
        run_dir.mkdir(parents=True)
        report = {
            "summary": {},
            "results": [
                {"case_id": "stable", "evaluator": "contains", "passed": True, "score": 1.0},
                {"case_id": "flaky", "evaluator": "contains", "passed": flaky_passed, "score": 1.0 if flaky_passed else 0.0},
            ],
        }
        (run_dir / "report.json").write_text(json.dumps(report), encoding="utf-8")
        (run_dir / "traces.jsonl").write_text("", encoding="utf-8")
        (run_dir / "manifest.json").write_text("{}", encoding="utf-8")

    report = analyze_suite_health(dataset, runs_path=runs)

    assert report["run_health"]["summary"]["saturated_cases"] == 1
    assert report["run_health"]["summary"]["flaky_cases"] == 1
    titles = {issue["title"] for issue in report["issues"]}
    assert "Case appears saturated across run history" in titles
    assert "Case has mixed pass/fail outcomes across run history" in titles


def test_suite_health_integrates_production_coverage_and_human_review(tmp_path: Path) -> None:
    dataset = tmp_path / "dataset.yaml"
    dataset.write_text(
        "metadata:\n  owner: eval-team\n  sources: [seed]\n"
        "cases:\n"
        "  - id: c1\n    input: refund\n    expected:\n      answer: ok\n    tags: [refund]\n    metadata:\n      capability: refunds\n      risk_level: high\n",
        encoding="utf-8",
    )
    production = tmp_path / "production.json"
    production.write_text(
        json.dumps({"events": [{"event_id": "e1", "input": "cancel", "tags": ["subscription"], "metadata": {"capability": "subscription", "risk_level": "critical"}}]}),
        encoding="utf-8",
    )
    human_review = tmp_path / "human-review.json"
    human_review.write_text(json.dumps({"summary": {"labeled": 1, "missing_labels": 0, "mismatches": 0}, "records": [{"item": {"case_id": "c1"}, "label": {"human_passed": True}}]}), encoding="utf-8")

    report = analyze_suite_health(dataset, production_path=production, human_review_path=human_review)

    assert report["summary"]["high_risk_without_review"] == 0
    assert report["summary"]["uncovered_production_segments"] > 0
    assert any(issue["category"] == "production_coverage" for issue in report["issues"])


def test_suite_health_flags_stale_and_invalid_high_risk_review_dates(tmp_path: Path) -> None:
    dataset = tmp_path / "dataset.yaml"
    dataset.write_text(
        "metadata:\n  owner: eval-team\n  sources: [seed]\n"
        "cases:\n"
        "  - id: stale\n    input: stale\n    expected:\n      answer: ok\n    metadata:\n      capability: safety\n      risk_level: high\n      last_reviewed_at: 2000-01-01\n"
        "  - id: invalid\n    input: invalid\n    expected:\n      answer: ok\n    metadata:\n      capability: safety\n      risk_level: critical\n      last_reviewed_at: not-a-date\n",
        encoding="utf-8",
    )

    report = analyze_suite_health(dataset, stale_days=90)

    titles = {issue["title"] for issue in report["issues"]}
    assert "High-risk case review evidence is stale" in titles
    assert "High-risk case has invalid review date" in titles
    assert report["summary"]["high_risk_without_review"] == 2


def test_suite_health_run_history_ignores_cases_outside_dataset(tmp_path: Path) -> None:
    dataset = tmp_path / "dataset.yaml"
    dataset.write_text(
        "metadata:\n  owner: eval-team\n  sources: [seed]\n"
        "cases:\n"
        "  - id: included\n    input: included\n    expected:\n      answer: ok\n    metadata:\n      capability: refunds\n      risk_level: low\n",
        encoding="utf-8",
    )
    runs = tmp_path / "runs"
    for index, outside_passed in enumerate([True, False, True], start=1):
        run_dir = runs / f"run{index}"
        run_dir.mkdir(parents=True)
        report = {
            "summary": {},
            "results": [
                {"case_id": "included", "evaluator": "contains", "passed": True, "score": 1.0},
                {"case_id": "outside", "evaluator": "contains", "passed": outside_passed, "score": 1.0 if outside_passed else 0.0},
            ],
        }
        (run_dir / "report.json").write_text(json.dumps(report), encoding="utf-8")
        (run_dir / "traces.jsonl").write_text("", encoding="utf-8")
        (run_dir / "manifest.json").write_text("{}", encoding="utf-8")

    report = analyze_suite_health(dataset, runs_path=runs)

    assert set(report["run_health"]["cases"]) == {"included"}
    assert report["run_health"]["summary"]["cases_with_history"] == 1
    assert all(issue.get("case_id") != "outside" for issue in report["issues"])


def test_suite_health_integrates_reference_validation_and_lifecycle(tmp_path: Path) -> None:
    dataset = tmp_path / "dataset.yaml"
    dataset.write_text(
        "metadata:\n  owner: eval-team\n  sources: [seed]\n  suite_type: regression\n  maturity: active\n"
        "cases:\n"
        "  - id: c1\n    input: q\n    expected:\n      answer: ok\n    metadata:\n      capability: core\n      risk_level: low\n      regression:\n        status: active\n"
        "  - id: c2\n    input: q2\n    expected:\n      answer: ok\n    reference:\n      final_output: ok\n    metadata:\n      capability: core\n      risk_level: low\n      regression:\n        status: active\n",
        encoding="utf-8",
    )
    reference = tmp_path / "reference.json"
    reference.write_text(
        json.dumps(
            {
                "summary": {"cases": 2, "failed": 1},
                "items": [
                    {"case_id": "c1", "status": "missing", "passed": False, "errors": ["missing"]},
                    {"case_id": "c2", "status": "passed", "passed": True, "errors": []},
                ],
            }
        ),
        encoding="utf-8",
    )

    report = analyze_suite_health(dataset, reference_validation_path=reference)

    titles = {issue["title"] for issue in report["issues"]}
    assert "Regression/safety suite is missing target_pass_rate" in titles
    assert "Case is missing reference solution" in titles
    assert "Reference solution failed validation" in titles
    assert report["summary"]["missing_reference"] == 1
    assert report["summary"]["failed_references"] == 1
    assert report["summary"]["lifecycle_issues"] == 1


    dataset = tmp_path / "dataset.yaml"
    dataset.write_text("cases:\n  - id: c1\n    input: q\n    expected:\n      answer: a\n", encoding="utf-8")
    report = analyze_suite_health(dataset)

    write_suite_health_json(tmp_path / "suite.json", report)
    write_suite_health_markdown(tmp_path / "suite.md", report)

    assert json.loads((tmp_path / "suite.json").read_text(encoding="utf-8"))["summary"]["cases"] == 1
    assert "AgentEval Suite Health Report" in (tmp_path / "suite.md").read_text(encoding="utf-8")
