import asyncio

from config import EvaluatorConfig
from evaluators.cost import CostEvaluator
from schemas import AgentRun, EvalCase, Usage


def test_cost_evaluator_budget_passes() -> None:
    case = EvalCase(id="c1", input="q", expected={"max_latency_ms": 1000, "max_total_tokens": 200})
    run = AgentRun(case_id="c1", latency_ms=100, usage=Usage(input_tokens=50, output_tokens=30))

    result = asyncio.run(CostEvaluator().evaluate(case, run))

    assert result.passed


def test_cost_evaluator_fails_input_budget() -> None:
    case = EvalCase(id="c1", input="q", expected={"max_input_tokens": 10})
    run = AgentRun(case_id="c1", usage=Usage(input_tokens=50))

    result = asyncio.run(CostEvaluator().evaluate(case, run))

    assert not result.passed
    assert "max_input_tokens" in result.failure_reason


def test_cost_evaluator_fails_output_budget() -> None:
    case = EvalCase(id="c1", input="q", expected={"max_output_tokens": 10})
    run = AgentRun(case_id="c1", usage=Usage(output_tokens=50))

    result = asyncio.run(CostEvaluator().evaluate(case, run))

    assert not result.passed


def test_cost_evaluator_fails_cache_miss_budget() -> None:
    case = EvalCase(id="c1", input="q", expected={"max_cache_miss_tokens": 20})
    run = AgentRun(case_id="c1", usage=Usage(input_tokens=10, cache_creation_input_tokens=20, cache_read_input_tokens=100))

    result = asyncio.run(CostEvaluator().evaluate(case, run))

    assert not result.passed
    assert result.metrics["cache_miss_tokens"] == 30


def test_cost_evaluator_fails_estimated_cost() -> None:
    config = EvaluatorConfig(type="cost", settings={"input_cost_per_million": 10, "output_cost_per_million": 20})
    case = EvalCase(id="c1", input="q", expected={"max_estimated_cost_usd": 0.000001})
    run = AgentRun(case_id="c1", usage=Usage(input_tokens=1000, output_tokens=1000))

    result = asyncio.run(CostEvaluator(config).evaluate(case, run))

    assert not result.passed
    assert result.metrics["estimated_cost_usd"] > 0
