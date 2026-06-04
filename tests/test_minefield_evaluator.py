import asyncio

from evaluators.minefield import MinefieldEvaluator
from schemas import AgentRun, EvalCase, ToolCall


def test_minefield_evaluator_passes_when_no_violations() -> None:
    case = EvalCase(id="c1", input="q", expected={"minefields": [{"id": "no_delete", "forbidden_tool": "delete_user"}]})
    run = AgentRun(case_id="c1", tool_calls=[ToolCall(name="lookup")])

    result = asyncio.run(MinefieldEvaluator().evaluate(case, run))

    assert result.passed


def test_minefield_evaluator_detects_forbidden_tool() -> None:
    case = EvalCase(id="c1", input="q", expected={"minefields": [{"id": "no_delete", "forbidden_tool": "delete_user"}]})
    run = AgentRun(case_id="c1", tool_calls=[ToolCall(name="delete_user")])

    result = asyncio.run(MinefieldEvaluator().evaluate(case, run))

    assert not result.passed
    assert result.failure_type == "minefield_violation"


def test_minefield_evaluator_detects_forbidden_output_regex() -> None:
    case = EvalCase(id="c1", input="q", expected={"minefields": [{"id": "no_secret", "forbidden_output_regex": "token"}]})
    run = AgentRun(case_id="c1", final_output="token=abc")

    result = asyncio.run(MinefieldEvaluator().evaluate(case, run))

    assert not result.passed


def test_minefield_evaluator_detects_forbidden_tool_argument() -> None:
    case = EvalCase(id="c1", input="q", expected={"minefields": [{"id": "no_force", "forbidden_tool_argument": {"name": "refund", "input": {"force": True}}}]})
    run = AgentRun(case_id="c1", tool_calls=[ToolCall(name="refund", input={"force": True, "order": "A100"})])

    result = asyncio.run(MinefieldEvaluator().evaluate(case, run))

    assert not result.passed


def test_minefield_evaluator_detects_forbidden_state() -> None:
    case = EvalCase(id="c1", input="q", expected={"minefields": [{"id": "no_delete", "forbidden_state": {"orders.A100.deleted": True}}]})
    run = AgentRun(case_id="c1", artifacts={"final_state": {"orders": {"A100": {"deleted": True}}}})

    result = asyncio.run(MinefieldEvaluator().evaluate(case, run))

    assert not result.passed
