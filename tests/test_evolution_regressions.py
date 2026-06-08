import json
from pathlib import Path

import yaml

from config import load_dataset
from evolution.regressions import append_regression_dataset, generate_regression_dataset, merge_regression_dataset, regression_fingerprint, write_regression_dataset


def _write_run(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)
    report = {
        "cases": [
            {"id": "c1", "input": "unsafe", "expected": {"should_refuse": True}, "tags": ["safety"], "evaluators": ["safety"]},
            {"id": "c2", "input": "weather", "expected": {"required_tools": ["weather"]}, "tags": ["tool-use"], "evaluators": ["trajectory"]},
        ],
        "results": [
            {"case_id": "c1", "evaluator": "safety", "passed": False, "failure_type": "unsafe", "failure_reason": "not refused"},
            {"case_id": "c2", "evaluator": "trajectory", "passed": True},
        ],
    }
    (path / "report.json").write_text(json.dumps(report), encoding="utf-8")
    (path / "traces.jsonl").write_text("", encoding="utf-8")


def test_generate_regression_dataset_from_failed_cases(tmp_path: Path) -> None:
    run_dir = tmp_path / "run"
    _write_run(run_dir)

    dataset = generate_regression_dataset(run_dir)

    assert dataset["metadata"]["generated_from_failures"] is True
    assert len(dataset["cases"]) == 1
    case = dataset["cases"][0]
    assert case["id"] == "regression_c1"
    assert case["tags"] == ["safety", "regression"]
    assert case["metadata"]["regression"]["source_case_id"] == "c1"
    assert case["metadata"]["regression"]["failed_evaluators"] == ["safety"]
    assert case["metadata"]["regression"]["failure_types"] == ["unsafe"]
    assert case["metadata"]["regression"]["fingerprint"]
    assert case["metadata"]["regression"]["status"] == "active"
    assert case["metadata"]["regression"]["severity"] == "medium"
    assert case["metadata"]["regression"]["first_seen_run"] == str(run_dir)
    assert case["metadata"]["regression"]["last_seen_run"] == str(run_dir)
    assert case["metadata"]["regression"]["seen_count"] == 1


def test_generate_regression_dataset_filters(tmp_path: Path) -> None:
    run_dir = tmp_path / "run"
    _write_run(run_dir)

    assert len(generate_regression_dataset(run_dir, tag="missing")["cases"]) == 0
    assert len(generate_regression_dataset(run_dir, evaluator="trajectory")["cases"]) == 0
    assert len(generate_regression_dataset(run_dir, failure_type="unsafe")["cases"]) == 1



def test_regression_fingerprint_is_stable_and_content_based() -> None:
    case = {"input": "unsafe", "expected": {"should_refuse": True}}

    first = regression_fingerprint(case, ["safety"], ["unsafe"], ["Not refused"])
    second = regression_fingerprint(case, ["safety"], ["unsafe"], ["not   refused"])
    different = regression_fingerprint(case, ["contains"], ["missing_fact"], ["not refused"])

    assert first == second
    assert first != different


def test_merge_regression_dataset_dedupes_and_updates_seen_count(tmp_path: Path) -> None:
    run_dir = tmp_path / "run"
    _write_run(run_dir)
    generated = generate_regression_dataset(run_dir)

    merged = merge_regression_dataset(generated, generated, dedupe=True)

    assert len(merged["cases"]) == 1
    regression = merged["cases"][0]["metadata"]["regression"]
    assert regression["seen_count"] == 2
    assert regression["last_seen_run"] == str(run_dir)


def test_append_regression_dataset_preserves_existing_and_loads(tmp_path: Path) -> None:
    run_dir = tmp_path / "run"
    _write_run(run_dir)
    generated = generate_regression_dataset(run_dir)
    out = tmp_path / "library.yaml"

    first = append_regression_dataset(out, generated, dedupe=True)
    second = append_regression_dataset(out, generated, dedupe=True)
    loaded = load_dataset(out)

    assert len(first["cases"]) == 1
    assert len(second["cases"]) == 1
    assert second["cases"][0]["metadata"]["regression"]["seen_count"] == 2
    assert len(loaded.cases) == 1

    out = tmp_path / "nested" / "regressions.yaml"
    write_regression_dataset(out, {"metadata": {"name": "r"}, "cases": []})

    assert yaml.safe_load(out.read_text(encoding="utf-8"))["metadata"]["name"] == "r"
