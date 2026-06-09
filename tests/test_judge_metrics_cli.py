import json
from pathlib import Path

from typer.testing import CliRunner

from cli import app


runner = CliRunner()


def test_judge_metrics_example_runs_offline(tmp_path: Path) -> None:
    out = tmp_path / "judge-metrics"

    result = runner.invoke(
        app,
        [
            "run",
            "--dataset",
            "examples/datasets/judge_metrics.yaml",
            "--config",
            "examples/configs/judge_metrics_eval.yaml",
            "--out",
            str(out),
        ],
    )

    assert result.exit_code == 0, result.output
    payload = json.loads((out / "report.json").read_text(encoding="utf-8"))
    evaluators = {item["evaluator"] for item in payload["results"]}
    assert {
        "answer_relevancy",
        "faithfulness",
        "context_relevancy",
        "context_precision",
        "context_recall",
        "task_completion",
        "hallucination",
        "conversation_quality",
    }.issubset(evaluators)
