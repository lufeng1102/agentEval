import asyncio
from pathlib import Path

from agents.static_adapter import StaticAgentAdapter
from config import AppConfig, EvaluatorConfig, RunnerConfig, load_config, load_dataset
from evaluators import build_evaluator
from runners import EvalExecutor
from schemas import AgentRun, EvalCase, EvalResult, RunContext


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


class FailThenSucceedAgent:
    def __init__(self) -> None:
        self.calls = 0

    async def run(self, case: EvalCase, context: RunContext) -> AgentRun:
        self.calls += 1
        if self.calls == 1:
            raise RuntimeError("temporary failure")
        return AgentRun(case_id=case.id, final_output="ok")


class AlwaysFailAgent:
    def __init__(self) -> None:
        self.calls = 0

    async def run(self, case: EvalCase, context: RunContext) -> AgentRun:
        self.calls += 1
        raise ValueError("permanent failure")


class SleepingAgent:
    async def run(self, case: EvalCase, context: RunContext) -> AgentRun:
        await asyncio.sleep(0.05)
        return AgentRun(case_id=case.id, final_output="late")


class NamedEvaluator:
    def __init__(self, name: str) -> None:
        self.name = name
        self.calls = 0

    async def evaluate(self, case: EvalCase, run: AgentRun) -> EvalResult:
        self.calls += 1
        return EvalResult(case_id=case.id, evaluator=self.name, score=1.0, passed=True)


def test_executor_retries_failed_agent_run(tmp_path: Path) -> None:
    case = EvalCase(id="c1", input="q")
    config = AppConfig(runner=RunnerConfig(retries=1), evaluators=[EvaluatorConfig(type="contains")])
    agent = FailThenSucceedAgent()
    evaluator = NamedEvaluator("contains")
    executor = EvalExecutor(agent, [evaluator], config)

    runs, results = asyncio.run(executor.run([case], tmp_path))

    assert agent.calls == 2
    assert len(runs) == 1
    assert runs[0].final_output == "ok"
    assert runs[0].errors == []
    assert len(results) == 1


def test_executor_records_error_after_retries_exhausted(tmp_path: Path) -> None:
    case = EvalCase(id="c1", input="q")
    config = AppConfig(runner=RunnerConfig(retries=1), evaluators=[EvaluatorConfig(type="contains")])
    agent = AlwaysFailAgent()
    evaluator = NamedEvaluator("contains")
    executor = EvalExecutor(agent, [evaluator], config)

    runs, results = asyncio.run(executor.run([case], tmp_path))

    assert agent.calls == 2
    assert runs[0].errors == ["ValueError: permanent failure"]
    assert len(results) == 1
    assert evaluator.calls == 1


def test_executor_records_timeout_as_run_error(tmp_path: Path) -> None:
    case = EvalCase(id="c1", input="q")
    config = AppConfig(runner=RunnerConfig(timeout_seconds=0.01), evaluators=[EvaluatorConfig(type="contains")])
    executor = EvalExecutor(SleepingAgent(), [NamedEvaluator("contains")], config)

    runs, _ = asyncio.run(executor.run([case], tmp_path))

    assert len(runs) == 1
    assert len(runs[0].errors) == 1
    assert runs[0].errors[0].startswith("TimeoutError:")


def test_executor_respects_case_evaluator_allowlist(tmp_path: Path) -> None:
    case = EvalCase(id="c1", input="q", evaluators=["selected"])
    config = AppConfig(evaluators=[EvaluatorConfig(type="contains")])
    selected = NamedEvaluator("selected")
    skipped = NamedEvaluator("skipped")
    executor = EvalExecutor(StaticAgentAdapter("ok"), [selected, skipped], config)

    _, results = asyncio.run(executor.run([case], tmp_path))

    assert [result.evaluator for result in results] == ["selected"]
    assert selected.calls == 1
    assert skipped.calls == 0


def test_executor_uses_case_timeout_override(tmp_path: Path) -> None:
    case = EvalCase(id="c1", input="q", timeout_seconds=0.01)
    config = AppConfig(runner=RunnerConfig(timeout_seconds=1), evaluators=[EvaluatorConfig(type="contains")])
    executor = EvalExecutor(SleepingAgent(), [NamedEvaluator("contains")], config)

    runs, _ = asyncio.run(executor.run([case], tmp_path))

    assert len(runs[0].errors) == 1
    assert runs[0].errors[0].startswith("TimeoutError:")
