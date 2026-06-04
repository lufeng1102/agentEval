from pathlib import Path

from typer.testing import CliRunner

from cli import app


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
