import asyncio

from config import EvaluatorConfig
from evaluators.cost import CostEvaluator
from evaluators.exact_match import ContainsEvaluator
from evaluators.safety import SafetyEvaluator
from evaluators.state import StateEvaluator
from evaluators.trajectory import TrajectoryEvaluator
from schemas import AgentRun, EvalCase, ToolCall, Usage


def test_contains_evaluator_fails_when_required_facts_are_empty() -> None:
    result = asyncio.run(ContainsEvaluator().evaluate(EvalCase(id="c1", input="q", expected={"required_facts": []}), AgentRun(case_id="c1", final_output="anything")))

    assert not result.passed
    assert result.score == 0
    assert result.metrics["required"] == []


def test_safety_evaluator_fails_when_forbidden_terms_present_without_refusal_requirement() -> None:
    case = EvalCase(id="c1", input="q", expected={"forbidden_terms": ["secret"]})
    run = AgentRun(case_id="c1", final_output="the secret is 123")

    result = asyncio.run(SafetyEvaluator().evaluate(case, run))

    assert not result.passed
    assert result.metrics["forbidden_present"] == ["secret"]


def test_safety_evaluator_fails_when_refusal_contains_forbidden_term() -> None:
    case = EvalCase(id="c1", input="q", expected={"should_refuse": True, "forbidden_terms": ["secret"]})
    run = AgentRun(case_id="c1", final_output="抱歉，不能提供 secret")

    result = asyncio.run(SafetyEvaluator().evaluate(case, run))

    assert not result.passed
    assert result.metrics["refused"] is True
    assert result.metrics["forbidden_present"] == ["secret"]


def test_cost_evaluator_includes_cache_write_cost_and_zero_usage_metrics() -> None:
    config = EvaluatorConfig(type="cost", settings={"input_cost_per_million": 1, "output_cost_per_million": 2})
    run = AgentRun(case_id="c1", usage=Usage(cache_creation_input_tokens=1_000_000))
    case = EvalCase(id="c1", input="q", expected={"max_estimated_cost_usd": 1.3})

    result = asyncio.run(CostEvaluator(config).evaluate(case, run))

    assert result.passed
    assert result.metrics["estimated_cost_usd"] == 1.25
    assert result.metrics["total_tokens"] == 1_000_000


def test_cost_evaluator_reports_no_expectations_with_zero_usage() -> None:
    result = asyncio.run(CostEvaluator().evaluate(EvalCase(id="c1", input="q"), AgentRun(case_id="c1")))

    assert not result.passed
    assert result.metrics["total_tokens"] == 0
    assert result.failure_reason == "no cost expectations configured"


def test_trajectory_evaluator_superset_mode_rejects_tools_outside_reference() -> None:
    case = EvalCase(
        id="c1",
        input="q",
        expected={"reference_trajectory": [{"name": "lookup"}], "trajectory": {"match_mode": "superset"}},
    )
    run = AgentRun(case_id="c1", tool_calls=[ToolCall(name="lookup"), ToolCall(name="extra")])

    result = asyncio.run(TrajectoryEvaluator().evaluate(case, run))

    assert not result.passed
    assert result.failure_type == "trajectory_mismatch"
    assert "outside reference" in result.failure_reason


def test_trajectory_evaluator_fails_when_no_expectations_configured() -> None:
    result = asyncio.run(TrajectoryEvaluator().evaluate(EvalCase(id="c1", input="q"), AgentRun(case_id="c1")))

    assert not result.passed
    assert result.failure_reason == "no trajectory expectations configured"
    assert result.metrics["called_tools"] == []


def test_state_evaluator_reports_missing_nested_path() -> None:
    case = EvalCase(id="c1", input="q", expected={"final_state": {"orders.A100.status": "cancelled"}})
    run = AgentRun(case_id="c1", artifacts={"final_state": {"orders": {}}})

    result = asyncio.run(StateEvaluator().evaluate(case, run))

    assert not result.passed
    assert result.failure_type == "state_mismatch"
    assert result.metrics["checks"][0]["actual"] is None
