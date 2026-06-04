from __future__ import annotations

from typing import Any

from evaluators.matching import get_path, value_matches
from schemas import AgentRun, EvalCase, EvalResult


class StateEvaluator:
    name = "state"

    async def evaluate(self, case: EvalCase, run: AgentRun) -> EvalResult:
        final_state = _final_state(case, run)
        expected_state = case.expected.get("final_state") or case.scenario.get("expected_state") or {}
        forbidden_state = case.expected.get("forbidden_state") or {}
        checks: list[dict[str, Any]] = []

        for assertion in _assertions(expected_state):
            exists, actual = get_path(final_state, assertion["path"])
            passed = exists and value_matches(assertion["value"], actual, assertion["match_mode"])
            checks.append({"type": "expected_state", "path": assertion["path"], "expected": assertion["value"], "actual": actual, "passed": passed})

        for assertion in _assertions(forbidden_state):
            exists, actual = get_path(final_state, assertion["path"])
            violated = exists and value_matches(assertion["value"], actual, assertion["match_mode"])
            checks.append({"type": "forbidden_state", "path": assertion["path"], "forbidden": assertion["value"], "actual": actual, "passed": not violated})

        if not checks:
            return EvalResult(case_id=case.id, evaluator=self.name, score=0, passed=False, metrics={"final_state": final_state}, failure_reason="no state expectations configured", failure_type="state_not_configured")

        passed_count = sum(item["passed"] for item in checks)
        failures = [item for item in checks if not item["passed"]]
        return EvalResult(
            case_id=case.id,
            evaluator=self.name,
            score=passed_count / len(checks),
            passed=not failures,
            metrics={"final_state": final_state, "checks": checks},
            failure_reason=f"state checks failed: {failures}" if failures else None,
            failure_type="state_mismatch" if failures else None,
        )


def _final_state(case: EvalCase, run: AgentRun) -> dict[str, Any]:
    if "final_state" in run.artifacts:
        return run.artifacts["final_state"]
    if run.raw_response and "final_state" in run.raw_response:
        return run.raw_response["final_state"]
    return case.scenario.get("final_state", {})


def _assertions(raw: Any) -> list[dict[str, Any]]:
    if isinstance(raw, list):
        return [
            {"path": str(item.get("path", "")), "value": item.get("value"), "match_mode": item.get("match_mode", "exact")}
            for item in raw
            if isinstance(item, dict)
        ]
    if isinstance(raw, dict):
        return [{"path": str(path), "value": value, "match_mode": "exact"} for path, value in raw.items()]
    return []
