import asyncio

import pytest

from config import EvaluatorConfig
from evaluators import build_evaluator
from schemas import AgentRun, EvalCase, EvalResult


class CustomAlwaysPassEvaluator:
    name = "custom_pass"

    def __init__(self, config=None):
        self.config = config

    async def evaluate(self, case: EvalCase, run: AgentRun) -> EvalResult:
        return EvalResult(case_id=case.id, evaluator=self.name, score=1, passed=True)


def build_custom_without_config():
    return CustomAlwaysPassEvaluator()


def build_custom_type_error(config):
    raise TypeError("plugin exploded")


def test_import_path_evaluator() -> None:
    evaluator = build_evaluator(EvaluatorConfig(type="import", settings={"import_path": "evaluators.exact_match.ContainsEvaluator"}))
    result = asyncio.run(evaluator.evaluate(EvalCase(id="c1", input="q", expected={"required_facts": ["ok"]}), AgentRun(case_id="c1", final_output="ok")))

    assert result.passed
    assert result.evaluator == "contains"


def test_import_evaluator_requires_import_path() -> None:
    with pytest.raises(ValueError, match="import evaluator requires settings.import_path"):
        build_evaluator(EvaluatorConfig(type="import"))


def test_import_evaluator_rejects_malformed_import_path() -> None:
    with pytest.raises(ValueError, match="invalid evaluator import path"):
        build_evaluator(EvaluatorConfig(type="import", settings={"import_path": "missingattr"}))


def test_import_evaluator_supports_factory_without_config() -> None:
    evaluator = build_evaluator(EvaluatorConfig(type="import", settings={"import_path": "tests.test_plugin_evaluator.build_custom_without_config"}))

    assert isinstance(evaluator, CustomAlwaysPassEvaluator)


def test_import_evaluator_type_error_falls_back_to_no_config_call() -> None:
    with pytest.raises(TypeError, match="missing 1 required positional argument"):
        build_evaluator(EvaluatorConfig(type="import", settings={"import_path": "tests.test_plugin_evaluator.build_custom_type_error"}))


def test_import_evaluator_reports_missing_attribute() -> None:
    with pytest.raises(AttributeError):
        build_evaluator(EvaluatorConfig(type="import", settings={"import_path": "tests.test_plugin_evaluator.missing"}))
