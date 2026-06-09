from __future__ import annotations

import fnmatch
import re
from typing import Any

from evaluators.matching import get_path, value_matches
from schemas import AgentRun, EvalCase, EvalResult


class EnvironmentEvaluator:
    name = "environment"

    async def evaluate(self, case: EvalCase, run: AgentRun) -> EvalResult:
        expected = case.expected.get("environment", {}) or {}
        env = run.artifacts.get("environment") or {}
        if not env:
            return EvalResult(case_id=case.id, repeat_index=run.repeat_index, evaluator=self.name, score=0, passed=False, failure_type="environment_missing", failure_reason="environment artifacts are missing")

        after_files = set(((env.get("after") or {}).get("files") or {}).keys())
        diff = env.get("diff") or {}
        created = set(diff.get("created") or [])
        modified = set(diff.get("modified") or [])
        deleted = set(diff.get("deleted") or [])
        touched = created | modified | deleted
        violations = []
        checks = []

        for pattern in expected.get("required_files", []) or []:
            ok = _has_match(after_files, pattern)
            checks.append(ok)
            if not ok:
                violations.append(f"required file missing: {pattern}")
        for pattern in expected.get("forbidden_files", []) or []:
            ok = not _has_match(after_files, pattern)
            checks.append(ok)
            if not ok:
                violations.append(f"forbidden file exists: {pattern}")
        for pattern in expected.get("required_modified_files", []) or []:
            ok = _has_match(created | modified, pattern)
            checks.append(ok)
            if not ok:
                violations.append(f"required modified file not touched: {pattern}")
        for pattern in expected.get("forbidden_modified_files", []) or []:
            matched = sorted(path for path in touched if _matches(path, pattern))
            ok = not matched
            checks.append(ok)
            if not ok:
                violations.append(f"forbidden modified files matched {pattern}: {matched}")
        if expected.get("max_modified_files") is not None:
            max_modified = int(expected["max_modified_files"])
            ok = len(touched) <= max_modified
            checks.append(ok)
            if not ok:
                violations.append(f"modified file count {len(touched)} exceeds max {max_modified}")
        for pattern in expected.get("no_deleted_files", []) or []:
            matched = sorted(path for path in deleted if _matches(path, pattern))
            ok = not matched
            checks.append(ok)
            if not ok:
                violations.append(f"deleted files matched {pattern}: {matched}")

        protected = diff.get("protected_path_violations") or []
        commands = env.get("commands") or []
        failed_commands = [command for command in commands if _command_failed(command)]
        _evaluate_commands(expected, commands, failed_commands, checks, violations)
        _evaluate_database(expected, env.get("database") or [], checks, violations)
        _evaluate_http(expected, env.get("http") or [], checks, violations)

        if protected:
            checks.append(False)
            violations.append(f"protected path violations: {protected}")

        passed = not violations
        score = sum(1 for item in checks if item) / len(checks) if checks else (1.0 if passed else 0.0)
        database = env.get("database") or []
        http = env.get("http") or []
        return EvalResult(
            case_id=case.id,
            repeat_index=run.repeat_index,
            evaluator=self.name,
            score=score,
            passed=passed,
            metrics={
                "created_files": len(created),
                "modified_files": len(modified),
                "deleted_files": len(deleted),
                "protected_path_violations": len(protected),
                "commands": len(commands),
                "command_failures": len(failed_commands),
                "failed_commands": [item.get("command") for item in failed_commands],
                "queries": len(database),
                "query_failures": sum(1 for item in database if item.get("error")),
                "http_checks": len(http),
                "http_failures": sum(1 for item in http if item.get("error") or item.get("status_code") is None),
                "violations": violations,
            },
            failure_type=None if passed else "environment_violation",
            failure_reason=None if passed else "; ".join(violations),
            artifacts={"environment": env},
        )


def _evaluate_commands(expected: dict[str, Any], commands: list[dict[str, Any]], failed_commands: list[dict[str, Any]], checks: list[bool], violations: list[str]) -> None:
    if expected.get("max_command_failures") is not None:
        max_failures = int(expected["max_command_failures"])
        ok = len(failed_commands) <= max_failures
        checks.append(ok)
        if not ok:
            violations.append(f"command failures {len(failed_commands)} exceeds max {max_failures}")
    for phase_key, phase in [("required_setup_success", "setup"), ("required_test_success", "test"), ("required_teardown_success", "teardown")]:
        if expected.get(phase_key) is not None:
            phase_commands = [command for command in commands if command.get("phase") == phase]
            ok = bool(phase_commands) and all(not _command_failed(command) for command in phase_commands)
            checks.append(ok)
            if not ok:
                violations.append(f"required {phase} commands did not all succeed")
    for command in expected.get("required_command_success", []) or []:
        matched = [item for item in commands if item.get("command") == command]
        ok = bool(matched) and all(not _command_failed(item) for item in matched)
        checks.append(ok)
        if not ok:
            violations.append(f"required command did not succeed: {command}")
    for command in expected.get("forbidden_command_failure", []) or []:
        matched = [item for item in commands if item.get("command") == command]
        ok = all(not _command_failed(item) for item in matched)
        checks.append(ok)
        if not ok:
            violations.append(f"forbidden command failure: {command}")
    for spec in expected.get("required_command_stdout", []) or []:
        command, pattern, mode = _command_output_spec(spec)
        matched = [item for item in commands if command is None or item.get("command") == command]
        ok = bool(matched) and any(_output_matches(item, pattern, mode) for item in matched)
        checks.append(ok)
        if not ok:
            violations.append(f"required command stdout not found: {pattern}")
    for spec in expected.get("forbidden_command_stdout", []) or []:
        command, pattern, mode = _command_output_spec(spec)
        matched = [item for item in commands if command is None or item.get("command") == command]
        ok = not any(_output_matches(item, pattern, mode) for item in matched)
        checks.append(ok)
        if not ok:
            violations.append(f"forbidden command stdout matched: {pattern}")


def _evaluate_database(expected: dict[str, Any], queries: list[dict[str, Any]], checks: list[bool], violations: list[str]) -> None:
    database_expected = expected.get("database") or {}
    if not database_expected:
        return
    failed = [query for query in queries if query.get("error")]
    if database_expected.get("max_query_failures") is not None:
        max_failures = int(database_expected["max_query_failures"])
        ok = len(failed) <= max_failures
        checks.append(ok)
        if not ok:
            violations.append(f"query failures {len(failed)} exceeds max {max_failures}")
    for query in database_expected.get("required_query_success", []) or []:
        matched = [item for item in queries if item.get("query") == query]
        ok = bool(matched) and all(not item.get("error") for item in matched)
        checks.append(ok)
        if not ok:
            violations.append(f"required query did not succeed: {query}")
    for spec in database_expected.get("required_rows", []) or []:
        matched = _matching_queries(queries, spec)
        minimum = int(spec.get("min_count", 1)) if isinstance(spec, dict) else 1
        ok = bool(matched) and any((item.get("row_count") or 0) >= minimum and not item.get("error") for item in matched)
        checks.append(ok)
        if not ok:
            violations.append(f"required rows not found: {_spec_label(spec)}")
    for spec in database_expected.get("forbidden_rows", []) or []:
        matched = _matching_queries(queries, spec)
        ok = all((item.get("row_count") or 0) == 0 for item in matched)
        checks.append(ok)
        if not ok:
            violations.append(f"forbidden rows found: {_spec_label(spec)}")


def _evaluate_http(expected: dict[str, Any], checks_data: list[dict[str, Any]], checks: list[bool], violations: list[str]) -> None:
    http_expected = expected.get("http") or {}
    if not http_expected:
        return
    failed = [check for check in checks_data if check.get("error") or check.get("status_code") is None]
    if http_expected.get("max_http_failures") is not None:
        max_failures = int(http_expected["max_http_failures"])
        ok = len(failed) <= max_failures
        checks.append(ok)
        if not ok:
            violations.append(f"http failures {len(failed)} exceeds max {max_failures}")
    for spec in http_expected.get("required_status", []) or []:
        matched = _matching_http(checks_data, spec)
        expected_status = int(spec.get("status") or spec.get("status_code"))
        ok = bool(matched) and any(item.get("status_code") == expected_status for item in matched)
        checks.append(ok)
        if not ok:
            violations.append(f"required http status not found: {_spec_label(spec)}")
    for spec in http_expected.get("required_json_paths", []) or []:
        matched = _matching_http(checks_data, spec)
        path = str(spec.get("path_expr") or spec.get("json_path") or spec.get("path"))
        expected_value = spec.get("value")
        mode = str(spec.get("match_mode") or "exact")
        ok = False
        for item in matched:
            exists, actual = get_path(item.get("json") or {}, path)
            if exists and value_matches(expected_value, actual, mode):
                ok = True
                break
        checks.append(ok)
        if not ok:
            violations.append(f"required http json path not matched: {path}")


def _command_failed(command: dict[str, Any]) -> bool:
    return bool(command.get("timed_out") or command.get("exit_code") is None or command.get("exit_code") != 0)


def _command_output_spec(spec: Any) -> tuple[str | None, str, str]:
    if isinstance(spec, str):
        return None, spec, "contains"
    return spec.get("command"), str(spec.get("contains") or spec.get("regex") or ""), "regex" if spec.get("regex") else "contains"


def _output_matches(command: dict[str, Any], pattern: str, mode: str) -> bool:
    output = f"{command.get('stdout') or ''}\n{command.get('stderr') or ''}"
    if mode == "regex":
        return re.search(pattern, output) is not None
    return pattern in output


def _matching_queries(queries: list[dict[str, Any]], spec: Any) -> list[dict[str, Any]]:
    if isinstance(spec, str):
        return [item for item in queries if item.get("query") == spec]
    query = spec.get("query")
    phase = spec.get("phase")
    return [item for item in queries if (query is None or item.get("query") == query) and (phase is None or item.get("phase") == phase)]


def _matching_http(checks: list[dict[str, Any]], spec: dict[str, Any]) -> list[dict[str, Any]]:
    url = spec.get("url")
    path = spec.get("path")
    method = spec.get("method")
    phase = spec.get("phase")
    return [item for item in checks if (url is None or item.get("url") == url) and (path is None or str(item.get("url", "")).endswith(str(path))) and (method is None or item.get("method") == str(method).upper()) and (phase is None or item.get("phase") == phase)]


def _spec_label(spec: Any) -> str:
    if isinstance(spec, str):
        return spec
    return str(spec.get("query") or spec.get("url") or spec.get("path") or spec)


def _has_match(paths: set[str], pattern: str) -> bool:
    return any(_matches(path, pattern) for path in paths)


def _matches(path: str, pattern: str) -> bool:
    return fnmatch.fnmatch(path, pattern) or fnmatch.fnmatch(path, pattern.rstrip("/**"))
