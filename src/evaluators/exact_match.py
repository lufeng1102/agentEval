from __future__ import annotations

from schemas import AgentRun, EvalCase, EvalResult


class ExactMatchEvaluator:
    name = "exact_match"

    async def evaluate(self, case: EvalCase, run: AgentRun) -> EvalResult:
        expected = str(case.expected.get("answer", "")).strip()
        actual = run.final_output.strip()
        passed = bool(expected) and actual == expected
        return EvalResult(
            case_id=case.id,
            evaluator=self.name,
            score=1.0 if passed else 0.0,
            passed=passed,
            metrics={"expected": expected, "actual": actual},
            failure_reason=None if passed else f"expected exact output {expected!r}, got {actual!r}",
        )


class ContainsEvaluator:
    name = "contains"

    async def evaluate(self, case: EvalCase, run: AgentRun) -> EvalResult:
        required = [str(item) for item in case.expected.get("required_facts", [])]
        output = run.final_output
        missing = [item for item in required if item not in output]
        passed = bool(required) and not missing
        score = 1.0 if passed else ((len(required) - len(missing)) / len(required) if required else 0.0)
        return EvalResult(
            case_id=case.id,
            evaluator=self.name,
            score=score,
            passed=passed,
            metrics={"required": required, "missing": missing},
            failure_reason=None if passed else f"missing required facts: {missing}",
        )
