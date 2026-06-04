import asyncio

from config import EvaluatorConfig
from evaluators import build_evaluator
from schemas import AgentRun, EvalCase, EvalResult


class CustomAlwaysPassEvaluator:
    name = "custom_pass"

    def __init__(self, config=None):
        self.config = config

    async def evaluate(self, case: EvalCase, run: AgentRun) -> EvalResult:
        return EvalResult(case_id=case.id, evaluator=self.name, score=1, passed=True)


def test_import_path_evaluator() -> None:
    evaluator = build_evaluator(EvaluatorConfig(type="import", settings={"import_path": "evaluators.exact_match.ContainsEvaluator"}))
    result = asyncio.run(evaluator.evaluate(EvalCase(id="c1", input="q", expected={"required_facts": ["ok"]}), AgentRun(case_id="c1", final_output="ok")))

    assert result.passed
    assert result.evaluator == "contains"
