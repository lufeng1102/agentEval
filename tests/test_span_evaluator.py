import asyncio

from evaluators.span import SpanEvaluator
from schemas import AgentRun, EvalCase, TraceSpan


def test_span_evaluator_checks_required_and_forbidden_names() -> None:
    case = EvalCase(id="c1", input="x", expected={"spans": {"required_names": ["search"], "forbidden_names": ["delete_user"], "max_error_spans": 0}})
    run = AgentRun(case_id="c1", spans=[TraceSpan(span_id="s1", name="search", kind="tool", status="ok")])

    result = asyncio.run(SpanEvaluator().evaluate(case, run))

    assert result.passed is True
    assert result.score == 1


def test_span_evaluator_fails_on_error_spans() -> None:
    case = EvalCase(id="c1", input="x", expected={"spans": {"max_error_spans": 0}})
    run = AgentRun(case_id="c1", spans=[TraceSpan(span_id="s1", name="search", kind="tool", status="error", error="boom")])

    result = asyncio.run(SpanEvaluator().evaluate(case, run))

    assert result.passed is False
    assert result.failure_type == "span_contract"


def test_span_evaluator_checks_required_attributes() -> None:
    case = EvalCase(id="c1", input="x", expected={"spans": {"required_attributes": [{"key": "openinference.span.kind", "value": "TOOL"}]}})
    run = AgentRun(case_id="c1", spans=[TraceSpan(span_id="s1", name="search", kind="tool", attributes={"openinference.span.kind": "TOOL"})])

    result = asyncio.run(SpanEvaluator().evaluate(case, run))

    assert result.passed is True
