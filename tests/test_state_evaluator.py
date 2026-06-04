import asyncio

from evaluators.state import StateEvaluator
from schemas import AgentRun, EvalCase


def test_state_evaluator_passes_expected_final_state() -> None:
    case = EvalCase(id="c1", input="q", expected={"final_state": {"orders.A100.status": "cancelled"}})
    run = AgentRun(case_id="c1", artifacts={"final_state": {"orders": {"A100": {"status": "cancelled"}}}})

    result = asyncio.run(StateEvaluator().evaluate(case, run))

    assert result.passed


def test_state_evaluator_fails_state_mismatch() -> None:
    case = EvalCase(id="c1", input="q", expected={"final_state": {"orders.A100.status": "cancelled"}})
    run = AgentRun(case_id="c1", artifacts={"final_state": {"orders": {"A100": {"status": "paid"}}}})

    result = asyncio.run(StateEvaluator().evaluate(case, run))

    assert not result.passed
    assert result.failure_type == "state_mismatch"


def test_state_evaluator_fails_forbidden_state() -> None:
    case = EvalCase(id="c1", input="q", expected={"forbidden_state": {"orders.A100.deleted": True}})
    run = AgentRun(case_id="c1", artifacts={"final_state": {"orders": {"A100": {"deleted": True}}}})

    result = asyncio.run(StateEvaluator().evaluate(case, run))

    assert not result.passed


def test_state_evaluator_uses_scenario_expected_state() -> None:
    case = EvalCase(id="c1", input="q", scenario={"expected_state": {"orders.A100.status": "cancelled"}})
    run = AgentRun(case_id="c1", artifacts={"final_state": {"orders": {"A100": {"status": "cancelled"}}}})

    result = asyncio.run(StateEvaluator().evaluate(case, run))

    assert result.passed
