from pathlib import Path

from typer.testing import CliRunner

from cli import app


runner = CliRunner()


def test_validate_passes_for_basic_dataset() -> None:
    result = runner.invoke(
        app,
        [
            "validate",
            "--dataset",
            "examples/datasets/basic_agent_eval.yaml",
            "--config",
            "examples/configs/static_eval.yaml",
        ],
    )

    assert result.exit_code == 0, result.output
    assert "Validation passed" in result.output


def test_validate_fails_when_case_references_unconfigured_evaluator(tmp_path: Path) -> None:
    dataset = tmp_path / "dataset.yaml"
    dataset.write_text(
        """
cases:
  - id: c1
    input: q
    evaluators: [regex]
    expected:
      regex: H2O
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

    result = runner.invoke(app, ["validate", "--dataset", str(dataset), "--config", str(config)])

    assert result.exit_code == 1
    assert "case c1 references evaluator 'regex'" in result.output


def test_validate_fails_when_required_expected_field_is_missing(tmp_path: Path) -> None:
    dataset = tmp_path / "dataset.yaml"
    dataset.write_text(
        """
cases:
  - id: c1
    input: q
    evaluators: [regex]
""".strip(),
        encoding="utf-8",
    )
    config = tmp_path / "config.yaml"
    config.write_text(
        """
agent:
  provider: static
evaluators:
  - type: regex
""".strip(),
        encoding="utf-8",
    )

    result = runner.invoke(app, ["validate", "--dataset", str(dataset), "--config", str(config)])



def test_validate_fails_when_rubric_judge_case_has_no_rubric(tmp_path: Path) -> None:
    dataset = tmp_path / "dataset.yaml"
    dataset.write_text(
        """
cases:
  - id: c1
    input: q
    evaluators: [rubric_judge]
""".strip(),
        encoding="utf-8",
    )
    config = tmp_path / "config.yaml"
    config.write_text(
        """
agent:
  provider: static
evaluators:
  - type: rubric_judge
""".strip(),
        encoding="utf-8",
    )

    result = runner.invoke(app, ["validate", "--dataset", str(dataset), "--config", str(config)])

    assert result.exit_code == 1
    assert "case c1 uses rubric_judge but rubric is missing" in result.output


def test_validate_allows_rubric_judge_with_rubric(tmp_path: Path) -> None:
    dataset = tmp_path / "dataset.yaml"
    dataset.write_text(
        """
cases:
  - id: c1
    input: q
    rubric: Answer according to the rubric.
    evaluators: [rubric_judge]
""".strip(),
        encoding="utf-8",
    )
    config = tmp_path / "config.yaml"
    config.write_text(
        """
agent:
  provider: static
evaluators:
  - type: rubric_judge
""".strip(),
        encoding="utf-8",
    )

    result = runner.invoke(app, ["validate", "--dataset", str(dataset), "--config", str(config)])

    assert result.exit_code == 0, result.output
    assert "Validation passed" in result.output


def test_validate_allows_trajectory_judge_without_static_expected_fields(tmp_path: Path) -> None:
    dataset = tmp_path / "dataset.yaml"
    dataset.write_text(
        """
cases:
  - id: c1
    input: q
    evaluators: [trajectory_judge]
""".strip(),
        encoding="utf-8",
    )
    config = tmp_path / "config.yaml"
    config.write_text(
        """
agent:
  provider: static
evaluators:
  - type: trajectory_judge
""".strip(),
        encoding="utf-8",
    )

    result = runner.invoke(app, ["validate", "--dataset", str(dataset), "--config", str(config)])

    assert result.exit_code == 0, result.output
    assert "Validation passed" in result.output
