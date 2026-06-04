import asyncio

from evaluators.json_schema import JsonSchemaEvaluator
from schemas import AgentRun, EvalCase


def test_json_schema_evaluator_passes_required_properties() -> None:
    case = EvalCase(id="c1", input="q", expected={"json_schema": {"type": "object", "required": ["answer"], "properties": {"answer": {"type": "string"}, "confidence": {"type": "number"}}}})
    run = AgentRun(case_id="c1", final_output='{"answer":"H2O","confidence":0.9}')

    result = asyncio.run(JsonSchemaEvaluator().evaluate(case, run))

    assert result.passed


def test_json_schema_evaluator_fails_non_json() -> None:
    case = EvalCase(id="c1", input="q", expected={"json_schema": {"type": "object"}})
    run = AgentRun(case_id="c1", final_output="not json")

    result = asyncio.run(JsonSchemaEvaluator().evaluate(case, run))

    assert not result.passed
    assert "valid JSON" in result.failure_reason


def test_json_schema_evaluator_fails_missing_required() -> None:
    case = EvalCase(id="c1", input="q", expected={"json_schema": {"type": "object", "required": ["answer"]}})
    run = AgentRun(case_id="c1", final_output="{}")

    result = asyncio.run(JsonSchemaEvaluator().evaluate(case, run))

    assert not result.passed
    assert "required property" in result.failure_reason


def test_json_schema_evaluator_fails_type_mismatch() -> None:
    case = EvalCase(id="c1", input="q", expected={"json_schema": {"type": "object", "properties": {"confidence": {"type": "number"}}}})
    run = AgentRun(case_id="c1", final_output='{"confidence":"high"}')

    result = asyncio.run(JsonSchemaEvaluator().evaluate(case, run))

    assert not result.passed
    assert "expected type number" in result.failure_reason


def test_json_schema_evaluator_validates_array_items() -> None:
    case = EvalCase(id="c1", input="q", expected={"json_schema": {"type": "array", "items": {"type": "integer"}}})
    run = AgentRun(case_id="c1", final_output="[1, 2, 3]")

    result = asyncio.run(JsonSchemaEvaluator().evaluate(case, run))

    assert result.passed
