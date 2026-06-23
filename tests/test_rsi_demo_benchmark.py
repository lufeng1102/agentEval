from __future__ import annotations

from pathlib import Path

from config import load_config, load_dataset
from evaluators.minefield import MinefieldEvaluator
from schemas import AgentRun, EvalCase, ToolCall


def test_rsi_demo_benchmark_dataset_and_config_load() -> None:
    dataset = load_dataset("examples/datasets/rsi_demo_benchmark.yaml")
    config = load_config("examples/configs/rsi_demo_benchmark.yaml")

    assert {case.id for case in dataset.cases} == {
        "rsi_eval_tampering_001",
        "rsi_holdout_leakage_001",
        "rsi_memory_poisoning_001",
        "rsi_action_risk_001",
        "rsi_self_mod_regression_001",
    }
    assert config.agent.provider == "static"
    assert {evaluator.type for evaluator in config.evaluators} >= {"contains", "trajectory", "minefield"}


def test_rsi_demo_minefield_catches_forbidden_action() -> None:
    dataset = load_dataset("examples/datasets/rsi_demo_benchmark.yaml")
    case = next(item for item in dataset.cases if item.id == "rsi_holdout_leakage_001")
    run = AgentRun(case_id=case.id, tool_calls=[ToolCall(name="access_holdout")])

    result = run_async(MinefieldEvaluator().evaluate(case, run))

    assert result.passed is False
    assert result.failure_type == "minefield_violation"


def test_rsi_demo_benchmark_cli_runs(tmp_path: Path) -> None:
    from typer.testing import CliRunner

    from cli import app

    result = CliRunner().invoke(
        app,
        [
            "run",
            "--dataset",
            "examples/datasets/rsi_demo_benchmark.yaml",
            "--config",
            "examples/configs/rsi_demo_benchmark.yaml",
            "--out",
            str(tmp_path / "rsi-demo"),
            "--fail-on-error",
        ],
    )

    assert result.exit_code == 0, result.output
    assert (tmp_path / "rsi-demo" / "report.json").exists()


def run_async(coro):
    import asyncio

    return asyncio.run(coro)
