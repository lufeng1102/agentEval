import json
from pathlib import Path

from typer.testing import CliRunner

from cli import app

runner = CliRunner()


def test_suite_health_cli_writes_json_and_markdown(tmp_path: Path) -> None:
    dataset = tmp_path / "dataset.yaml"
    dataset.write_text("metadata:\n  owner: eval-team\n  sources: [seed]\ncases:\n  - id: c1\n    input: q\n    expected:\n      answer: a\n    metadata:\n      capability: support\n      risk_level: low\n", encoding="utf-8")

    result = runner.invoke(app, ["suite-health", "--dataset", str(dataset), "--out", str(tmp_path / "suite-health"), "--format", "json", "--format", "markdown"])

    assert result.exit_code == 0, result.output
    assert (tmp_path / "suite-health.json").exists()
    assert (tmp_path / "suite-health.md").exists()
    assert json.loads((tmp_path / "suite-health.json").read_text(encoding="utf-8"))["summary"]["cases"] == 1


def test_suite_health_cli_fail_on_high(tmp_path: Path) -> None:
    dataset = tmp_path / "dataset.yaml"
    dataset.write_text("cases:\n  - id: c1\n    input: q\n", encoding="utf-8")

    result = runner.invoke(app, ["suite-health", "--dataset", str(dataset), "--out", str(tmp_path / "suite-health.md"), "--fail-on", "high"])

    assert result.exit_code == 1
    assert "Suite health threshold failed" in result.output


def test_suite_health_cli_rejects_bad_fail_on(tmp_path: Path) -> None:
    dataset = tmp_path / "dataset.yaml"
    dataset.write_text("cases:\n  - id: c1\n    input: q\n    expected:\n      answer: a\n", encoding="utf-8")

    result = runner.invoke(app, ["suite-health", "--dataset", str(dataset), "--fail-on", "severe"])

    assert result.exit_code != 0
    assert "--fail-on must be one of" in result.output
