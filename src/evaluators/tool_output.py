from __future__ import annotations

from typing import Any

from schemas import AgentRun, EvalCase, EvalResult, ToolCall


class ToolOutputEvaluator:
    name = "tool_output"

    async def evaluate(self, case: EvalCase, run: AgentRun) -> EvalResult:
        expected_outputs = case.expected.get("tool_outputs", []) or []
        if not expected_outputs:
            return EvalResult(
                case_id=case.id,
                evaluator=self.name,
                score=0,
                passed=False,
                failure_reason="expected.tool_outputs is not configured",
            )

        matched: list[dict[str, Any]] = []
        mismatches: list[dict[str, Any]] = []
        missing: list[dict[str, Any]] = []
        for item in expected_outputs:
            expected = _normalize_expected(item)
            calls = [call for call in run.tool_calls if call.name == expected["name"]]
            if not calls:
                missing.append({"name": expected["name"], "reason": "tool was not called"})
                continue

            match = _first_matching_call(expected, calls)
            if match:
                matched.append(match)
            else:
                mismatches.append(
                    {
                        "name": expected["name"],
                        "expected": expected["output"],
                        "match_mode": expected["match_mode"],
                        "actual_outputs": [call.output for call in calls],
                    }
                )

        total = len(expected_outputs)
        passed_count = len(matched)
        passed = not missing and not mismatches
        return EvalResult(
            case_id=case.id,
            evaluator=self.name,
            score=passed_count / total if total else 0,
            passed=passed,
            metrics={"matched": matched, "missing": missing, "mismatches": mismatches},
            failure_reason=_failure_reason(missing, mismatches),
        )


def _normalize_expected(item: Any) -> dict[str, Any]:
    if isinstance(item, str):
        return {"name": item, "output": None, "match_mode": "contains"}
    return {
        "name": str(item.get("name", "")),
        "output": item.get("output"),
        "match_mode": item.get("match_mode", "contains"),
    }


def _first_matching_call(expected: dict[str, Any], calls: list[ToolCall]) -> dict[str, Any] | None:
    for index, call in enumerate(calls):
        if _matches(expected["output"], call.output, expected["match_mode"]):
            return {"name": expected["name"], "call_index": index, "output": call.output}
    return None


def _matches(expected: Any, actual: Any, match_mode: str) -> bool:
    if match_mode == "exact":
        return actual == expected
    return _contains(expected, actual)


def _contains(expected: Any, actual: Any) -> bool:
    if expected is None:
        return actual is not None
    if isinstance(expected, dict):
        if not isinstance(actual, dict):
            return False
        return all(key in actual and _contains(value, actual[key]) for key, value in expected.items())
    if isinstance(expected, list):
        if not isinstance(actual, list):
            return False
        return all(any(_contains(expected_item, actual_item) for actual_item in actual) for expected_item in expected)
    if isinstance(expected, str) and isinstance(actual, str):
        return expected in actual
    return actual == expected


def _failure_reason(missing: list[dict[str, Any]], mismatches: list[dict[str, Any]]) -> str | None:
    reasons: list[str] = []
    if missing:
        reasons.append(f"missing tool outputs: {missing}")
    if mismatches:
        reasons.append(f"tool output mismatches: {mismatches}")
    return "; ".join(reasons) if reasons else None
