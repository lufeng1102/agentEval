import asyncio

from evaluators.regex import RegexEvaluator
from schemas import AgentRun, EvalCase


def test_regex_evaluator_include_passes() -> None:
    case = EvalCase(id="c1", input="q", expected={"regex": [r"订单号[:：]\s*\d+"]})
    run = AgentRun(case_id="c1", final_output="订单号: 12345")

    result = asyncio.run(RegexEvaluator().evaluate(case, run))

    assert result.passed


def test_regex_evaluator_include_fails() -> None:
    case = EvalCase(id="c1", input="q", expected={"regex": {"include": ["H2O"]}})
    run = AgentRun(case_id="c1", final_output="CO2")

    result = asyncio.run(RegexEvaluator().evaluate(case, run))

    assert not result.passed
    assert result.metrics["missing"] == ["H2O"]


def test_regex_evaluator_exclude_fails() -> None:
    case = EvalCase(id="c1", input="q", expected={"regex": {"exclude": ["密码"]}})
    run = AgentRun(case_id="c1", final_output="密码是 123456")

    result = asyncio.run(RegexEvaluator().evaluate(case, run))

    assert not result.passed
    assert result.metrics["present_forbidden"] == ["密码"]


def test_regex_evaluator_flags() -> None:
    case = EvalCase(id="c1", input="q", expected={"regex": {"include": ["^hello"], "flags": ["ignorecase", "multiline"]}})
    run = AgentRun(case_id="c1", final_output="first\nHello world")

    result = asyncio.run(RegexEvaluator().evaluate(case, run))

    assert result.passed
