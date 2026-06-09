import asyncio

from evaluators.tests import TestsEvaluator
from schemas import AgentRun, EvalCase


def test_tests_evaluator_passes_fail_to_pass_and_pass_to_pass() -> None:
    command = "python -m pytest tests/test_bug.py"
    stable = "python -m pytest tests/test_existing.py"
    case = EvalCase(id="c1", input="fix", expected={"tests": {"fail_to_pass": [{"command": command}], "pass_to_pass": [{"command": stable}], "require_all_test_commands_pass": True, "max_test_failures": 0}})
    run = AgentRun(case_id="c1", artifacts={"environment": {"commands": [{"phase": "test", "command": command, "exit_code": 0, "timed_out": False}, {"phase": "test", "command": stable, "exit_code": 0, "timed_out": False}]}})

    result = asyncio.run(TestsEvaluator().evaluate(case, run))

    assert result.passed is True
    assert result.score == 1.0


def test_tests_evaluator_fails_fail_to_pass() -> None:
    command = "python -m pytest tests/test_bug.py"
    case = EvalCase(id="c1", input="fix", expected={"tests": {"fail_to_pass": [{"command": command}]}})
    run = AgentRun(case_id="c1", artifacts={"environment": {"commands": [{"phase": "test", "command": command, "exit_code": 1, "timed_out": False}]}})

    result = asyncio.run(TestsEvaluator().evaluate(case, run))

    assert result.passed is False
    assert result.failure_type == "fail_to_pass_failed"


def test_tests_evaluator_fails_pass_to_pass_regression() -> None:
    command = "python -m pytest tests/test_existing.py"
    case = EvalCase(id="c1", input="fix", expected={"tests": {"pass_to_pass": [{"command": command}]}})
    run = AgentRun(case_id="c1", artifacts={"environment": {"commands": [{"phase": "test", "command": command, "exit_code": 2, "timed_out": False}]}})

    result = asyncio.run(TestsEvaluator().evaluate(case, run))

    assert result.passed is False
    assert result.failure_type == "pass_to_pass_regression"
