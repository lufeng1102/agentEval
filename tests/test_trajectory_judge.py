import asyncio

from config import EvaluatorConfig
from evaluators.trajectory_judge import TrajectoryJudgeEvaluator
from schemas import AgentRun, EvalCase, ToolCall


def test_trajectory_judge_uses_mock_judgement_pass() -> None:
    evaluator = TrajectoryJudgeEvaluator(EvaluatorConfig(type="trajectory_judge", settings={"mock_judgement": {"score": 0.9, "passed": True, "reasoning": "good"}}))

    result = asyncio.run(evaluator.evaluate(EvalCase(id="c1", input="q"), AgentRun(case_id="c1", tool_calls=[ToolCall(name="lookup")])))

    assert result.passed
    assert result.score == 0.9


def test_trajectory_judge_uses_case_mock_judgement_fail() -> None:
    evaluator = TrajectoryJudgeEvaluator(EvaluatorConfig(type="trajectory_judge"))
    case = EvalCase(id="c1", input="q", expected={"trajectory_judgement": {"score": 0.2, "passed": False, "reasoning": "bad path"}})

    result = asyncio.run(evaluator.evaluate(case, AgentRun(case_id="c1")))

    assert not result.passed
    assert result.failure_type == "trajectory_judge_failure"
