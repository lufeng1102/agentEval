from pathlib import Path

from typer.testing import CliRunner

from cli import app


def test_dynamic_cli_runs_example_dataset(tmp_path: Path) -> None:
    result = CliRunner().invoke(
        app,
        [
            "run",
            "--dataset",
            "examples/datasets/dynamic_agent_eval.yaml",
            "--config",
            "examples/configs/static_eval.yaml",
            "--out",
            str(tmp_path / "dynamic"),
        ],
    )

    assert result.exit_code == 0, result.output
    assert (tmp_path / "dynamic" / "report.json").exists()
    assert (tmp_path / "dynamic" / "traces.jsonl").exists()
    traces = (tmp_path / "dynamic" / "traces.jsonl").read_text(encoding="utf-8")
    assert '"dynamic"' in traces
    assert '"stop_reason"' in traces
