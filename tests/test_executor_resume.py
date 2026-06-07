import asyncio

from agents.base import AgentAdapter
from config import AppConfig, EvaluatorConfig, RunnerConfig
from evaluators.exact_match import ContainsEvaluator
from runners import EvalExecutor
from schemas import AgentRun, EvalCase, RunContext


class CountingAgent:
    def __init__(self) -> None:
        self.calls = 0

    async def run(self, case: EvalCase, context: RunContext) -> AgentRun:
        self.calls += 1
        return AgentRun(case_id=case.id, final_output="ok")


def test_executor_resume_reuses_existing_trace_and_runs_missing_repeats(tmp_path) -> None:
    case = EvalCase(id="c1", input="q", expected={"required_facts": ["ok"]}, evaluators=["contains"])
    config = AppConfig(runner=RunnerConfig(repeats=2), evaluators=[EvaluatorConfig(type="contains")])
    first_agent = CountingAgent()
    first_executor = EvalExecutor(first_agent, [ContainsEvaluator()], config)

    first_runs, first_results = asyncio.run(first_executor.run([case], tmp_path))
    assert first_agent.calls == 2
    assert len(first_runs) == 2
    assert len(first_results) == 2

    # Simulate an interrupted run that already completed repeat 0 only.
    traces = tmp_path / "traces.jsonl"
    traces.write_text(traces.read_text(encoding="utf-8").splitlines()[0] + "\n", encoding="utf-8")

    resume_agent = CountingAgent()
    resume_executor = EvalExecutor(resume_agent, [ContainsEvaluator()], config)
    resumed_runs, resumed_results = asyncio.run(resume_executor.run([case], tmp_path, resume=True))

    assert resume_agent.calls == 1
    assert len(resumed_runs) == 2
    assert {run.repeat_index for run in resumed_runs} == {0, 1}
    assert len(resumed_results) == 2
