import asyncio

from evaluators.environment import EnvironmentEvaluator
from schemas import AgentRun, EvalCase


def test_environment_evaluator_passes_required_modification() -> None:
    case = EvalCase(id="c1", input="fix", expected={"environment": {"required_modified_files": ["src/auth.py"], "forbidden_modified_files": ["tests/**"], "max_modified_files": 2}})
    run = AgentRun(
        case_id="c1",
        artifacts={
            "environment": {
                "after": {"files": {"src/auth.py": {}}},
                "diff": {"created": [], "modified": ["src/auth.py"], "deleted": [], "protected_path_violations": []},
            }
        },
    )

    result = asyncio.run(EnvironmentEvaluator().evaluate(case, run))

    assert result.passed is True
    assert result.score == 1.0


def test_environment_evaluator_fails_forbidden_modification() -> None:
    case = EvalCase(id="c1", input="fix", expected={"environment": {"forbidden_modified_files": ["tests/**"]}})
    run = AgentRun(
        case_id="c1",
        artifacts={
            "environment": {
                "after": {"files": {"tests/hidden.txt": {}}},
                "diff": {"created": ["tests/hidden.txt"], "modified": [], "deleted": [], "protected_path_violations": ["tests/hidden.txt"]},
            }
        },
    )

    result = asyncio.run(EnvironmentEvaluator().evaluate(case, run))

    assert result.passed is False
    assert result.failure_type == "environment_violation"
    assert "forbidden modified files" in result.failure_reason


def test_environment_evaluator_fails_when_artifacts_missing() -> None:
    case = EvalCase(id="c1", input="fix", expected={"environment": {"required_files": ["src/auth.py"]}})

    result = asyncio.run(EnvironmentEvaluator().evaluate(case, AgentRun(case_id="c1")))

    assert result.passed is False
    assert result.failure_type == "environment_missing"
def test_environment_evaluator_checks_required_command_success() -> None:
    command = "python -m pytest tests/test_auth.py"
    case = EvalCase(id="c1", input="fix", expected={"environment": {"required_command_success": [command], "max_command_failures": 0}})
    run = AgentRun(case_id="c1", artifacts={"environment": {"after": {"files": {}}, "diff": {"created": [], "modified": [], "deleted": [], "protected_path_violations": []}, "commands": [{"phase": "test", "command": command, "exit_code": 0, "timed_out": False}]}})

    result = asyncio.run(EnvironmentEvaluator().evaluate(case, run))

    assert result.passed is True
    assert result.metrics["command_failures"] == 0


def test_environment_evaluator_fails_required_command_failure() -> None:
    command = "python -m pytest tests/test_auth.py"
    case = EvalCase(id="c1", input="fix", expected={"environment": {"required_command_success": [command], "max_command_failures": 0}})
    run = AgentRun(case_id="c1", artifacts={"environment": {"after": {"files": {}}, "diff": {"created": [], "modified": [], "deleted": [], "protected_path_violations": []}, "commands": [{"phase": "test", "command": command, "exit_code": 1, "timed_out": False}]}})

    result = asyncio.run(EnvironmentEvaluator().evaluate(case, run))

    assert result.passed is False
    assert "required command did not succeed" in result.failure_reason
    assert result.metrics["command_failures"] == 1


def test_environment_evaluator_checks_required_test_success_and_stdout() -> None:
    command = "python -m pytest tests/test_auth.py"
    case = EvalCase(id="c1", input="fix", expected={"environment": {"required_test_success": True, "required_command_stdout": [{"command": command, "contains": "passed"}]}})
    run = AgentRun(case_id="c1", artifacts={"environment": {"after": {"files": {}}, "diff": {"created": [], "modified": [], "deleted": [], "protected_path_violations": []}, "commands": [{"phase": "test", "command": command, "exit_code": 0, "timed_out": False, "stdout": "1 passed"}]}})

    result = asyncio.run(EnvironmentEvaluator().evaluate(case, run))

    assert result.passed is True


def test_environment_evaluator_fails_forbidden_command_stdout() -> None:
    command = "python -m pytest tests/test_auth.py"
    case = EvalCase(id="c1", input="fix", expected={"environment": {"forbidden_command_stdout": [{"command": command, "regex": "FAILED|ERROR"}]}})
    run = AgentRun(case_id="c1", artifacts={"environment": {"after": {"files": {}}, "diff": {"created": [], "modified": [], "deleted": [], "protected_path_violations": []}, "commands": [{"phase": "test", "command": command, "exit_code": 0, "timed_out": False, "stdout": "FAILED"}]}})

    result = asyncio.run(EnvironmentEvaluator().evaluate(case, run))

    assert result.passed is False
    assert "forbidden command stdout" in result.failure_reason
