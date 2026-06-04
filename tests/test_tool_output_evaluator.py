import asyncio

from evaluators.tool_output import ToolOutputEvaluator
from schemas import AgentRun, EvalCase, ToolCall


def test_tool_output_dict_contains_passes() -> None:
    case = EvalCase(id="c1", input="q", expected={"tool_outputs": [{"name": "weather", "output": {"city": "北京"}}]})
    run = AgentRun(case_id="c1", tool_calls=[ToolCall(name="weather", output={"city": "北京", "condition": "晴"})])

    result = asyncio.run(ToolOutputEvaluator().evaluate(case, run))

    assert result.passed


def test_tool_output_dict_contains_fails() -> None:
    case = EvalCase(id="c1", input="q", expected={"tool_outputs": [{"name": "weather", "output": {"city": "北京"}}]})
    run = AgentRun(case_id="c1", tool_calls=[ToolCall(name="weather", output={"city": "上海"})])

    result = asyncio.run(ToolOutputEvaluator().evaluate(case, run))

    assert not result.passed
    assert result.metrics["mismatches"]


def test_tool_output_exact_passes() -> None:
    case = EvalCase(id="c1", input="q", expected={"tool_outputs": [{"name": "calculator", "output": 42, "match_mode": "exact"}]})
    run = AgentRun(case_id="c1", tool_calls=[ToolCall(name="calculator", output=42)])

    result = asyncio.run(ToolOutputEvaluator().evaluate(case, run))

    assert result.passed


def test_tool_output_string_contains_passes() -> None:
    case = EvalCase(id="c1", input="q", expected={"tool_outputs": [{"name": "summarize", "output": "出行建议"}]})
    run = AgentRun(case_id="c1", tool_calls=[ToolCall(name="summarize", output="这里是北京出行建议")])

    result = asyncio.run(ToolOutputEvaluator().evaluate(case, run))

    assert result.passed


def test_tool_output_list_contains_passes() -> None:
    case = EvalCase(id="c1", input="q", expected={"tool_outputs": [{"name": "search", "output": ["a", "b"]}]})
    run = AgentRun(case_id="c1", tool_calls=[ToolCall(name="search", output=["b", "a", "c"])])

    result = asyncio.run(ToolOutputEvaluator().evaluate(case, run))

    assert result.passed


def test_tool_output_multiple_calls_one_match_passes() -> None:
    case = EvalCase(id="c1", input="q", expected={"tool_outputs": [{"name": "weather", "output": {"city": "北京"}}]})
    run = AgentRun(
        case_id="c1",
        tool_calls=[ToolCall(name="weather", output={"city": "上海"}), ToolCall(name="weather", output={"city": "北京"})],
    )

    result = asyncio.run(ToolOutputEvaluator().evaluate(case, run))

    assert result.passed
