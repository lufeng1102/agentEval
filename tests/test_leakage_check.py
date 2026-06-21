import json
from pathlib import Path

from typer.testing import CliRunner

from cli import app
from evolution.leakage import analyze_leakage, write_leakage_json, write_leakage_markdown


runner = CliRunner()


def test_leakage_check_flags_answer_exposure_and_config_risks(tmp_path: Path) -> None:
    dataset = tmp_path / "dataset.yaml"
    dataset.write_text(
        """
cases:
  - id: c1
    input: The hidden answer is swordfish.
    expected:
      answer: swordfish
    metadata:
      suite_type: holdout
""".strip(),
        encoding="utf-8",
    )
    config = tmp_path / "config.yaml"
    config.write_text(
        """
environment:
  type: none
  reset_between_trials: false
  include_patterns: [reference_solution.txt]
""".strip(),
        encoding="utf-8",
    )

    report = analyze_leakage(dataset, config)

    titles = {issue["title"] for issue in report["issues"]}
    assert "Expected answer appears in case input" in titles
    assert "Environment does not reset between trials" in titles
    assert report["summary"]["issues"] >= 2


def test_leakage_check_cli_fails_on_high(tmp_path: Path) -> None:
    dataset = tmp_path / "dataset.yaml"
    dataset.write_text("cases:\n  - id: c1\n    input: hidden answer is okay\n    expected:\n      answer: okay\n", encoding="utf-8")
    out = tmp_path / "leakage.json"

    result = runner.invoke(app, ["leakage-check", "--dataset", str(dataset), "--out", str(out), "--format", "json", "--fail-on", "high"])

    assert result.exit_code == 1
    assert json.loads(out.read_text(encoding="utf-8"))["summary"]["high"] == 1


def test_leakage_check_uses_dataset_level_holdout_suite_type(tmp_path: Path) -> None:
    dataset = tmp_path / "dataset.yaml"
    dataset.write_text(
        """
metadata:
  suite_type: holdout
cases:
  - id: c1
    input: q
    expected:
      answer: ok
""".strip(),
        encoding="utf-8",
    )

    report = analyze_leakage(dataset)

    assert any(issue["title"] == "Holdout case lacks explicit holdout marker" for issue in report["issues"])


    report = {"dataset": "d", "config": None, "run": None, "summary": {"issues": 0, "critical": 0, "high": 0, "medium": 0, "low": 0}, "issues": [], "recommendations": []}

    write_leakage_json(tmp_path / "leakage.json", report)
    write_leakage_markdown(tmp_path / "leakage.md", report)

    assert json.loads((tmp_path / "leakage.json").read_text(encoding="utf-8"))["summary"]["issues"] == 0
    assert "Leakage / Anti-Cheat" in (tmp_path / "leakage.md").read_text(encoding="utf-8")
