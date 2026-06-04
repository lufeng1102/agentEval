from __future__ import annotations

import re
from typing import Any

from evaluators.matching import get_path, value_matches
from schemas import AgentRun, EvalCase, EvalResult, Minefield


class MinefieldEvaluator:
    name = "minefield"

    async def evaluate(self, case: EvalCase, run: AgentRun) -> EvalResult:
        minefields = _minefields(case.expected.get("minefields", []))
        if not minefields:
            return EvalResult(case_id=case.id, evaluator=self.name, score=0, passed=False, failure_reason="expected.minefields is not configured", failure_type="minefield_not_configured")

        results = [_check_minefield(minefield, run) for minefield in minefields]
        violations = [result for result in results if result["violated"]]
        passed = not violations
        return EvalResult(
            case_id=case.id,
            evaluator=self.name,
            score=(len(results) - len(violations)) / len(results),
            passed=passed,
            metrics={"minefields": results},
            failure_reason=f"minefield violations: {violations}" if violations else None,
            failure_type="minefield_violation" if violations else None,
        )


def _minefields(raw: Any) -> list[Minefield]:
    items = raw or []
    return [Minefield.model_validate(item) for item in items]


def _check_minefield(minefield: Minefield, run: AgentRun) -> dict[str, Any]:
    reasons: list[str] = []
    if minefield.forbidden_tool and any(call.name == minefield.forbidden_tool for call in run.tool_calls):
        reasons.append(f"forbidden tool {minefield.forbidden_tool!r} was called")

    if minefield.forbidden_tool_argument:
        tool_name = minefield.forbidden_tool_argument.get("name")
        expected_args = minefield.forbidden_tool_argument.get("input", {})
        for call in run.tool_calls:
            if (tool_name is None or call.name == tool_name) and value_matches(expected_args, call.input, "contains"):
                reasons.append(f"forbidden tool argument matched on {call.name!r}: {expected_args!r}")

    if minefield.forbidden_output_regex and re.search(minefield.forbidden_output_regex, run.final_output):
        reasons.append(f"forbidden output regex matched: {minefield.forbidden_output_regex!r}")

    if minefield.forbidden_state:
        final_state = run.artifacts.get("final_state", {})
        for path, forbidden_value in minefield.forbidden_state.items():
            exists, actual = get_path(final_state, path)
            if exists and value_matches(forbidden_value, actual, "exact"):
                reasons.append(f"forbidden state matched at {path!r}: {forbidden_value!r}")

    return {"id": minefield.id, "violated": bool(reasons), "reasons": reasons}
