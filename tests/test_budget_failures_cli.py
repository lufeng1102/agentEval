import json
from pathlib import Path

from typer.testing import CliRunner

from cli import app


runner = CliRunner()


def test_run_fails_when_budget_token_limit_exceeded(tmp_path: Path) -> None:
    dataset = tmp_path / "dataset.yaml"
    dataset.write_text("cases:\n  - id: c1\n    input: q\n    evaluators: [contains]\n    expected:\n      required_facts: [ok]\n", encoding="utf-8")
    config = tmp_path / "config.yaml"
    config.write_text(
        """
agent:
  provider: static
  static_response: ok
  static_artifacts:
    usage:
      input_tokens: 10
      output_tokens: 5
evaluators:
  - type: contains
report:
  formats: [json]
""".strip(),
        encoding="utf-8",
    )

    result = runner.invoke(app, ["run", "--dataset", str(dataset), "--config", str(config), "--out", str(tmp_path / "run"), "--max-total-tokens", "10"])

    assert result.exit_code == 1
    assert "total tokens" in result.output


def test_failures_command_clusters_failure_reasons(tmp_path: Path) -> None:
    report = tmp_path / "report.json"
    report.write_text(
        json.dumps(
            {
                "results": [
                    {"case_id": "c1", "evaluator": "contains", "score": 0, "passed": False, "failure_reason": "missing required facts: ['A']", "failure_type": "missing_fact"},
                    {"case_id": "c2", "evaluator": "contains", "score": 0, "passed": False, "failure_reason": "missing required facts: ['B']", "failure_type": "missing_fact"},
                    {"case_id": "c3", "evaluator": "safety", "score": 0, "passed": False, "failure_reason": "safety expectation was not met"},
                ]
            }
        ),
        encoding="utf-8",
    )

    result = runner.invoke(app, ["failures", "--report", str(report)])

    assert result.exit_code == 0, result.output


def test_run_fails_when_estimated_cost_exceeds_budget(tmp_path: Path) -> None:
    dataset = tmp_path / "dataset.yaml"
    dataset.write_text("cases:\n  - id: c1\n    input: q\n    evaluators: [contains]\n    expected:\n      required_facts: [ok]\n", encoding="utf-8")
    config = tmp_path / "config.yaml"
    config.write_text(
        """
agent:
  provider: static
  static_response: ok
  static_artifacts:
    usage:
      input_tokens: 1000000
      output_tokens: 1000000
evaluators:
  - type: contains
  - type: cost
    settings:
      input_cost_per_million: 1
      output_cost_per_million: 1
report:
  formats: [json]
""".strip(),
        encoding="utf-8",
    )

    result = runner.invoke(app, ["run", "--dataset", str(dataset), "--config", str(config), "--out", str(tmp_path / "run"), "--max-total-cost-usd", "1.5"])

    assert result.exit_code == 1
    assert "estimated cost" in result.output


def test_run_passes_cost_budget_when_rates_are_missing(tmp_path: Path) -> None:
    dataset = tmp_path / "dataset.yaml"
    dataset.write_text("cases:\n  - id: c1\n    input: q\n    evaluators: [contains]\n    expected:\n      required_facts: [ok]\n", encoding="utf-8")
    config = tmp_path / "config.yaml"
    config.write_text(
        """
agent:
  provider: static
  static_response: ok
  static_artifacts:
    usage:
      input_tokens: 1000000
      output_tokens: 1000000
evaluators:
  - type: contains
report:
  formats: [json]
""".strip(),
        encoding="utf-8",
    )

    result = runner.invoke(app, ["run", "--dataset", str(dataset), "--config", str(config), "--out", str(tmp_path / "run"), "--max-total-cost-usd", "0"])

    assert result.exit_code == 0, result.output
