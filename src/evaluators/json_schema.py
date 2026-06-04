from __future__ import annotations

import json
from typing import Any

from schemas import AgentRun, EvalCase, EvalResult


class JsonSchemaEvaluator:
    name = "json_schema"

    async def evaluate(self, case: EvalCase, run: AgentRun) -> EvalResult:
        schema = case.expected.get("json_schema")
        if not schema:
            return EvalResult(
                case_id=case.id,
                evaluator=self.name,
                score=0,
                passed=False,
                failure_reason="expected.json_schema is not configured",
            )

        try:
            parsed = json.loads(run.final_output)
        except json.JSONDecodeError as exc:
            return EvalResult(
                case_id=case.id,
                evaluator=self.name,
                score=0,
                passed=False,
                metrics={"parse_error": str(exc)},
                failure_reason=f"output is not valid JSON: {exc}",
            )

        errors = _validate_schema(parsed, schema, path="$")
        return EvalResult(
            case_id=case.id,
            evaluator=self.name,
            score=0.0 if errors else 1.0,
            passed=not errors,
            metrics={"parsed": parsed, "errors": errors},
            failure_reason="; ".join(errors) if errors else None,
        )


def _validate_schema(value: Any, schema: dict[str, Any], path: str) -> list[str]:
    errors: list[str] = []
    expected_type = schema.get("type")
    if expected_type and not _type_matches(value, expected_type):
        errors.append(f"{path}: expected type {expected_type}, got {_json_type(value)}")
        return errors

    if "enum" in schema and value not in schema["enum"]:
        errors.append(f"{path}: value {value!r} not in enum {schema['enum']!r}")

    if isinstance(value, dict):
        required = schema.get("required", []) or []
        for key in required:
            if key not in value:
                errors.append(f"{path}.{key}: required property missing")

        properties = schema.get("properties", {}) or {}
        for key, child_schema in properties.items():
            if key in value:
                errors.extend(_validate_schema(value[key], child_schema, f"{path}.{key}"))

    if isinstance(value, list) and "items" in schema:
        item_schema = schema["items"]
        for index, item in enumerate(value):
            errors.extend(_validate_schema(item, item_schema, f"{path}[{index}]"))

    return errors


def _type_matches(value: Any, expected_type: str | list[str]) -> bool:
    if isinstance(expected_type, list):
        return any(_type_matches(value, item) for item in expected_type)
    if expected_type == "object":
        return isinstance(value, dict)
    if expected_type == "array":
        return isinstance(value, list)
    if expected_type == "string":
        return isinstance(value, str)
    if expected_type == "number":
        return isinstance(value, int | float) and not isinstance(value, bool)
    if expected_type == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    if expected_type == "boolean":
        return isinstance(value, bool)
    if expected_type == "null":
        return value is None
    return False


def _json_type(value: Any) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, dict):
        return "object"
    if isinstance(value, list):
        return "array"
    if isinstance(value, str):
        return "string"
    if isinstance(value, int):
        return "integer"
    if isinstance(value, float):
        return "number"
    return type(value).__name__
