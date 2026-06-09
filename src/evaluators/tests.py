from __future__ import annotations

from typing import Any

from schemas import AgentRun, EvalCase, EvalResult


class TestsEvaluator:
    name = "tests"

    async def evaluate(self, case: EvalCase, run: AgentRun) -> EvalResult:
        expected = case.expected.get("tests", {}) or {}
        env = run.artifacts.get("environment") or {}
        commands = [command for command in env.get("commands", []) or [] if command.get("phase") == "test"]
        if not expected:
            return EvalResult(case_id=case.id, repeat_index=run.repeat_index, evaluator=self.name, score=0, passed=False, failure_type="tests_missing_expectations", failure_reason="expected.tests is missing")
        checks: list[bool] = []
        failures: list[tuple[str, str]] = []

        for spec in expected.get("fail_to_pass", []) or []:
            command = _spec_command(spec)
            ok = _command_succeeded(commands, command)
            checks.append(ok)
            if not ok:
                failures.append(("fail_to_pass_failed", f"fail-to-pass command did not pass: {command}"))
        for spec in expected.get("pass_to_pass", []) or []:
            command = _spec_command(spec)
            ok = _command_succeeded(commands, command)
            checks.append(ok)
            if not ok:
                failures.append(("pass_to_pass_regression", f"pass-to-pass command regressed: {command}"))
        if expected.get("require_all_test_commands_pass") is not None:
            ok = bool(commands) and all(not _failed(command) for command in commands)
            checks.append(ok)
            if not ok:
                failures.append(("test_command_failure", "not all test commands passed"))
        if expected.get("max_test_failures") is not None:
            failed_count = sum(1 for command in commands if _failed(command))
            ok = failed_count <= int(expected["max_test_failures"])
            checks.append(ok)
            if not ok:
                failures.append(("test_command_failure", f"test command failures {failed_count} exceeds max {expected['max_test_failures']}"))

        passed = not failures
        score = sum(1 for item in checks if item) / len(checks) if checks else 0
        return EvalResult(
            case_id=case.id,
            repeat_index=run.repeat_index,
            evaluator=self.name,
            score=score,
            passed=passed,
            metrics={
                "test_commands": len(commands),
                "test_failures": sum(1 for command in commands if _failed(command)),
                "failed_commands": [command.get("command") for command in commands if _failed(command)],
            },
            failure_type=None if passed else failures[0][0],
            failure_reason=None if passed else "; ".join(reason for _, reason in failures),
            artifacts={"test_commands": commands},
        )


def _spec_command(spec: Any) -> str:
    if isinstance(spec, str):
        return spec
    return str(spec.get("command", ""))


def _command_succeeded(commands: list[dict[str, Any]], command: str) -> bool:
    matched = [item for item in commands if item.get("command") == command]
    return bool(matched) and all(not _failed(item) for item in matched)


def _failed(command: dict[str, Any]) -> bool:
    return bool(command.get("timed_out") or command.get("exit_code") is None or command.get("exit_code") != 0)
