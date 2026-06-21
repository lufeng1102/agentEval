import json
from pathlib import Path

from typer.testing import CliRunner

from cli import app
from evolution.references import validate_references_sync, write_reference_validation_json, write_reference_validation_markdown


runner = CliRunner()


def test_reference_validate_passes_reference_output(tmp_path: Path) -> None:
    dataset = tmp_path / "dataset.yaml"
    dataset.write_text(
        """
cases:
  - id: c1
    input: What is the answer?
    expected:
      required_facts: [forty two]
    reference:
      final_output: The answer is forty two.
""".strip(),
        encoding="utf-8",
    )
    config = tmp_path / "config.yaml"
    config.write_text(
        """
agent:
  provider: static
evaluators:
  - type: contains
""".strip(),
        encoding="utf-8",
    )

    report = validate_references_sync(dataset, config)

    assert report["summary"]["cases"] == 1
    assert report["summary"]["passed"] == 1
    assert report["items"][0]["status"] == "passed"


def test_reference_validate_reports_missing_and_failed_references(tmp_path: Path) -> None:
    dataset = tmp_path / "dataset.yaml"
    dataset.write_text(
        """
cases:
  - id: missing
    input: q
    expected:
      required_facts: [ok]
  - id: failed
    input: q
    expected:
      required_facts: [ok]
    metadata:
      reference:
        final_output: nope
""".strip(),
        encoding="utf-8",
    )
    config = tmp_path / "config.yaml"
    config.write_text("evaluators:\n  - type: contains\n", encoding="utf-8")

    report = validate_references_sync(dataset, config)

    assert report["summary"]["missing_reference"] == 1
    assert report["summary"]["failed"] == 2
    assert {item["status"] for item in report["items"]} == {"missing", "failed"}


def test_reference_validate_loads_jsonl_trace_file(tmp_path: Path) -> None:
    trace = tmp_path / "traces.jsonl"
    trace.write_text(json.dumps({"case_id": "c1", "final_output": "ok"}) + "\n", encoding="utf-8")
    dataset = tmp_path / "dataset.yaml"
    dataset.write_text(
        f"""
cases:
  - id: c1
    input: q
    expected:
      answer: ok
    reference:
      trace_file: {trace.name}
""".strip(),
        encoding="utf-8",
    )
    config = tmp_path / "config.yaml"
    config.write_text("evaluators:\n  - type: exact_match\n", encoding="utf-8")

    report = validate_references_sync(dataset, config)

    assert report["summary"]["passed"] == 1


    dataset = tmp_path / "dataset.yaml"
    dataset.write_text("cases:\n  - id: c1\n    input: q\n    expected:\n      required_facts: [ok]\n", encoding="utf-8")
    config = tmp_path / "config.yaml"
    config.write_text("evaluators:\n  - type: contains\n", encoding="utf-8")
    out = tmp_path / "reference.json"

    result = runner.invoke(app, ["reference-validate", "--dataset", str(dataset), "--config", str(config), "--out", str(out), "--format", "json", "--fail-on-error"])

    assert result.exit_code == 1
    payload = json.loads(out.read_text(encoding="utf-8"))
    assert payload["summary"]["missing_reference"] == 1


def test_reference_validation_writers(tmp_path: Path) -> None:
    report = {"dataset": "d", "config": "c", "summary": {"cases": 0, "with_reference": 0, "missing_reference": 0, "passed": 0, "failed": 0}, "items": []}

    write_reference_validation_json(tmp_path / "reference.json", report)
    write_reference_validation_markdown(tmp_path / "reference.md", report)

    assert json.loads((tmp_path / "reference.json").read_text(encoding="utf-8"))["summary"]["cases"] == 0
    assert "AgentEval Reference Validation" in (tmp_path / "reference.md").read_text(encoding="utf-8")
