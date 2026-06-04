import asyncio

from agents.static_adapter import StaticAgentAdapter
from config import AppConfig, EvaluatorConfig, RunnerConfig
from evaluators.exact_match import ContainsEvaluator
from runners import EvalExecutor
from schemas import EvalCase


def test_executor_repeats_and_stability_summary(tmp_path) -> None:
    case = EvalCase(id="c1", input="q", expected={"required_facts": ["ok"]}, evaluators=["contains"])
    config = AppConfig(runner=RunnerConfig(repeats=3), evaluators=[EvaluatorConfig(type="contains")])
    executor = EvalExecutor(StaticAgentAdapter("ok"), [ContainsEvaluator()], config)

    runs, results = asyncio.run(executor.run([case], tmp_path))

    assert len(runs) == 3
    assert len(results) == 3
    assert {run.repeat_index for run in runs} == {0, 1, 2}
    assert {result.repeat_index for result in results} == {0, 1, 2}
