from pathlib import Path

import pytest
from typer.testing import CliRunner

from cli import _discover_configs, app


def test_cli_matrix_runs_multiple_configs(tmp_path: Path) -> None:
    config_a = tmp_path / "a.yaml"
    config_b = tmp_path / "b.yaml"
    config_text = Path("examples/configs/static_eval.yaml").read_text(encoding="utf-8")
    config_a.write_text(config_text, encoding="utf-8")
    config_b.write_text(config_text, encoding="utf-8")

    result = CliRunner().invoke(
        app,
        [
            "matrix",
            "--dataset",
            "examples/datasets/basic_agent_eval.yaml",
            "--config",
            str(config_a),
            "--config",
            str(config_b),
            "--out",
            str(tmp_path / "matrix"),
        ],
    )

    assert result.exit_code == 0, result.output
    assert (tmp_path / "matrix" / "matrix.md").exists()
    assert (tmp_path / "matrix" / "a" / "report.json").exists()
    assert (tmp_path / "matrix" / "b" / "report.json").exists()


def test_discover_configs_reads_mixed_yaml_directory(tmp_path: Path) -> None:
    yaml_path = tmp_path / "a.yaml"
    yml_path = tmp_path / "b.yml"
    ignored = tmp_path / "notes.txt"
    yaml_path.write_text("agent: {}\n", encoding="utf-8")
    yml_path.write_text("agent: {}\n", encoding="utf-8")
    ignored.write_text("ignore", encoding="utf-8")

    assert _discover_configs([tmp_path]) == [yaml_path, yml_path]


def test_discover_configs_expands_globs(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    configs = tmp_path / "configs"
    configs.mkdir()
    one = configs / "one.yaml"
    two = configs / "two.yaml"
    one.write_text("agent: {}\n", encoding="utf-8")
    two.write_text("agent: {}\n", encoding="utf-8")
    monkeypatch.chdir(tmp_path)

    assert _discover_configs([Path("configs/*.yaml")]) == [one.relative_to(tmp_path), two.relative_to(tmp_path)]


def test_cli_matrix_fails_when_no_config_files_found(tmp_path: Path) -> None:
    empty_configs = tmp_path / "configs"
    empty_configs.mkdir()

    result = CliRunner().invoke(
        app,
        [
            "matrix",
            "--dataset",
            "examples/datasets/basic_agent_eval.yaml",
            "--config",
            str(empty_configs),
            "--out",
            str(tmp_path / "matrix"),
        ],
    )

    assert result.exit_code != 0
    assert "no config files found" in result.output


def test_cli_matrix_writes_baseline_comparison_report(tmp_path: Path) -> None:
    config_a = tmp_path / "a.yaml"
    config_b = tmp_path / "b.yaml"
    config_text = Path("examples/configs/static_eval.yaml").read_text(encoding="utf-8")
    config_a.write_text(config_text, encoding="utf-8")
    config_b.write_text(config_text, encoding="utf-8")

    result = CliRunner().invoke(
        app,
        [
            "matrix",
            "--dataset",
            "examples/datasets/basic_agent_eval.yaml",
            "--config",
            str(config_a),
            "--config",
            str(config_b),
            "--out",
            str(tmp_path / "matrix"),
        ],
    )

    assert result.exit_code == 0, result.output
    assert (tmp_path / "matrix" / "compare-a-vs-b.md").exists()
    matrix = (tmp_path / "matrix" / "matrix.md").read_text(encoding="utf-8")
    assert "compare-a-vs-b.md" in matrix
