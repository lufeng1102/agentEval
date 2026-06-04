import asyncio
from pathlib import Path

from agents.static_adapter import StaticAgentAdapter
from config import load_config, load_dataset
from evaluators import build_evaluator
from runners import EvalExecutor


def test_executor_writes_traces_and_results(tmp_path: Path) -> None:
    dataset = load_dataset(Path("examples/datasets/basic_agent_eval.yaml"))
    config = load_config(Path("examples/configs/static_eval.yaml"))
    agent = StaticAgentAdapter(
        "H2O。抱歉，我不能帮助入侵邮箱。北京天气适合出行建议。",
        tool_calls=config.agent.static_tool_calls,
        latency_ms=config.agent.static_latency_ms,
    )
    evaluators = [build_evaluator(item) for item in config.evaluators]
    executor = EvalExecutor(agent=agent, evaluators=evaluators, config=config)

    runs, results = asyncio.run(executor.run(dataset.cases, tmp_path))

    assert len(runs) == 12
    assert results
    assert (tmp_path / "traces.jsonl").exists()
    assert (tmp_path / "results.jsonl").exists()
