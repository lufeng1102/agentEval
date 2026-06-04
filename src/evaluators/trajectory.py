from __future__ import annotations

from collections import Counter
from typing import Any

from pydantic import ValidationError

from schemas import AgentRun, EvalCase, EvalResult, ExpectedToolCall, Milestone, ToolCall, TrajectoryPolicy


class TrajectoryEvaluator:
    name = "trajectory"

    async def evaluate(self, case: EvalCase, run: AgentRun) -> EvalResult:
        expected = case.expected
        policy = _trajectory_policy(expected)
        reference = _reference_trajectory(expected)
        called_tools = [call.name for call in run.tool_calls]
        checks: list[tuple[str, bool, str | None]] = []
        argument_mismatches: list[dict[str, Any]] = []

        required_tools = [str(tool) for tool in expected.get("required_tools", [])]
        missing_tools = [tool for tool in required_tools if tool not in called_tools]
        if required_tools:
            checks.append(("required_tools", not missing_tools, f"missing required tool calls: {missing_tools}" if missing_tools else None))

        forbidden_tools = [str(tool) for tool in expected.get("forbidden_tools", [])]
        forbidden_called = [tool for tool in called_tools if tool in forbidden_tools]
        if forbidden_tools:
            checks.append(("forbidden_tools", not forbidden_called, f"forbidden tools were called: {forbidden_called}" if forbidden_called else None))

        max_tool_calls = expected.get("max_tool_calls")
        if max_tool_calls is not None:
            passed = len(run.tool_calls) <= int(max_tool_calls)
            checks.append(("max_tool_calls", passed, f"tool call count {len(run.tool_calls)} exceeded {max_tool_calls}" if not passed else None))

        max_latency_ms = expected.get("max_latency_ms")
        if max_latency_ms is not None:
            passed = run.latency_ms <= float(max_latency_ms)
            checks.append(("max_latency_ms", passed, f"latency {run.latency_ms:.0f}ms exceeded {float(max_latency_ms):.0f}ms" if not passed else None))

        if reference:
            trajectory_passed, trajectory_reason, argument_mismatches = _match_trajectory(
                reference=reference,
                actual=run.tool_calls,
                policy=policy,
            )
            checks.append(("reference_trajectory", trajectory_passed, trajectory_reason))

        milestones = _milestones(expected)
        milestone_results = _check_milestones(milestones, run)
        if milestone_results:
            failed = [result for result in milestone_results if not result["passed"]]
            checks.append(("milestones", not failed, f"failed milestones: {[item['id'] for item in failed]}" if failed else None))

        if not checks:
            return EvalResult(
                case_id=case.id,
                evaluator=self.name,
                score=0,
                passed=False,
                metrics={"called_tools": called_tools},
                failure_reason="no trajectory expectations configured",
            )

        passed_count = sum(passed for _, passed, _ in checks)
        score = passed_count / len(checks)
        passed = passed_count == len(checks)
        failures = [reason for _, check_passed, reason in checks if not check_passed and reason]

        return EvalResult(
            case_id=case.id,
            evaluator=self.name,
            score=score,
            passed=passed,
            metrics={
                "called_tools": called_tools,
                "required_tools": required_tools,
                "missing_tools": missing_tools,
                "forbidden_tools": forbidden_tools,
                "forbidden_called": forbidden_called,
                "tool_call_count": len(run.tool_calls),
                "max_tool_calls": max_tool_calls,
                "latency_ms": run.latency_ms,
                "max_latency_ms": max_latency_ms,
                "trajectory_match_mode": policy.match_mode,
                "check_arguments": policy.check_arguments,
                "allow_extra_tools": policy.allow_extra_tools,
                "argument_mismatches": argument_mismatches,
                "milestone_results": milestone_results,
                "progress_rate": _progress_rate(milestone_results),
                "checks": [{"name": name, "passed": check_passed, "reason": reason} for name, check_passed, reason in checks],
            },
            failure_reason="; ".join(failures) if failures else None,
            failure_type=_failure_type(checks),
        )


def _trajectory_policy(expected: dict[str, Any]) -> TrajectoryPolicy:
    raw = expected.get("trajectory", {}) or {}
    if not isinstance(raw, dict):
        raw = {"match_mode": str(raw)}
    return TrajectoryPolicy.model_validate(raw)


def _reference_trajectory(expected: dict[str, Any]) -> list[ExpectedToolCall]:
    raw = expected.get("reference_trajectory") or expected.get("tool_calls") or []
    calls: list[ExpectedToolCall] = []
    for item in raw:
        if isinstance(item, str):
            calls.append(ExpectedToolCall(name=item))
        else:
            calls.append(ExpectedToolCall.model_validate(item))
    return calls


def _milestones(expected: dict[str, Any]) -> list[Milestone]:
    milestones: list[Milestone] = []
    for item in expected.get("milestones", []) or []:
        try:
            milestones.append(Milestone.model_validate(item))
        except ValidationError:
            continue
    return milestones


def _match_trajectory(
    reference: list[ExpectedToolCall],
    actual: list[ToolCall],
    policy: TrajectoryPolicy,
) -> tuple[bool, str | None, list[dict[str, Any]]]:
    if policy.match_mode == "strict":
        return _match_strict(reference, actual, policy)
    if policy.match_mode == "unordered":
        return _match_unordered(reference, actual, policy)
    if policy.match_mode == "subset":
        return _match_subset(reference, actual, policy)
    if policy.match_mode == "superset":
        return _match_superset(reference, actual, policy)
    return _match_subset(reference, actual, policy)


def _match_strict(
    reference: list[ExpectedToolCall], actual: list[ToolCall], policy: TrajectoryPolicy
) -> tuple[bool, str | None, list[dict[str, Any]]]:
    mismatches: list[dict[str, Any]] = []
    if len(reference) != len(actual):
        return False, f"strict trajectory length mismatch: expected {len(reference)}, got {len(actual)}", mismatches
    for index, expected_call in enumerate(reference):
        ok, reason = _call_matches(expected_call, actual[index], policy.check_arguments)
        if not ok:
            mismatches.append({"index": index, "expected": expected_call.model_dump(), "actual": actual[index].model_dump(), "reason": reason})
    return not mismatches, f"strict trajectory mismatches: {mismatches}" if mismatches else None, mismatches


def _match_unordered(
    reference: list[ExpectedToolCall], actual: list[ToolCall], policy: TrajectoryPolicy
) -> tuple[bool, str | None, list[dict[str, Any]]]:
    expected_counts = Counter(call.name for call in reference)
    actual_counts = Counter(call.name for call in actual)
    if expected_counts != actual_counts:
        return False, f"unordered trajectory tool counts mismatch: expected {dict(expected_counts)}, got {dict(actual_counts)}", []
    return _match_each_reference(reference, actual, policy.check_arguments)


def _match_subset(
    reference: list[ExpectedToolCall], actual: list[ToolCall], policy: TrajectoryPolicy
) -> tuple[bool, str | None, list[dict[str, Any]]]:
    passed, reason, mismatches = _match_each_reference(reference, actual, policy.check_arguments)
    if not passed:
        return passed, reason, mismatches
    if not policy.allow_extra_tools and len(actual) != len(reference):
        return False, "extra tool calls are not allowed", mismatches
    return True, None, mismatches


def _match_superset(
    reference: list[ExpectedToolCall], actual: list[ToolCall], policy: TrajectoryPolicy
) -> tuple[bool, str | None, list[dict[str, Any]]]:
    reference_names = {call.name for call in reference}
    extra = [call.name for call in actual if call.name not in reference_names]
    if extra:
        return False, f"actual trajectory contains tools outside reference: {extra}", []
    return _match_each_reference(actual=[ToolCall(name=call.name, input=call.input) for call in reference], reference=[ExpectedToolCall(name=call.name, input=call.input, match_mode=call.match_mode) for call in reference], check_arguments=policy.check_arguments)


def _match_each_reference(
    reference: list[ExpectedToolCall], actual: list[ToolCall], check_arguments: bool
) -> tuple[bool, str | None, list[dict[str, Any]]]:
    remaining = list(actual)
    mismatches: list[dict[str, Any]] = []
    for expected_call in reference:
        match_index = None
        candidate_reasons: list[str] = []
        for index, actual_call in enumerate(remaining):
            ok, reason = _call_matches(expected_call, actual_call, check_arguments)
            if ok:
                match_index = index
                break
            if actual_call.name == expected_call.name and reason:
                candidate_reasons.append(reason)
        if match_index is None:
            mismatches.append({"expected": expected_call.model_dump(), "reason": "; ".join(candidate_reasons) or "no matching tool call"})
        else:
            remaining.pop(match_index)
    return not mismatches, f"trajectory reference mismatches: {mismatches}" if mismatches else None, mismatches


def _call_matches(expected: ExpectedToolCall, actual: ToolCall, check_arguments: bool) -> tuple[bool, str | None]:
    if expected.name != actual.name:
        return False, f"expected tool {expected.name!r}, got {actual.name!r}"
    if not check_arguments:
        return True, None
    if expected.match_mode == "exact" and actual.input != expected.input:
        return False, f"arguments differ: expected exact {expected.input!r}, got {actual.input!r}"
    if expected.match_mode == "contains":
        missing = {key: value for key, value in expected.input.items() if actual.input.get(key) != value}
        if missing:
            return False, f"arguments missing/different: {missing!r}, actual {actual.input!r}"
    return True, None


def _check_milestones(milestones: list[Milestone], run: AgentRun) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    achieved: set[str] = set()
    pending = list(milestones)
    while pending:
        progressed = False
        for milestone in list(pending):
            unmet_dependencies = [dep for dep in milestone.depends_on if dep not in achieved]
            if unmet_dependencies:
                continue
            result = _check_milestone(milestone, run, unmet_dependencies=[])
            results.append(result)
            if result["passed"]:
                achieved.add(milestone.id)
            pending.remove(milestone)
            progressed = True
        if not progressed:
            for milestone in pending:
                unmet_dependencies = [dep for dep in milestone.depends_on if dep not in achieved]
                results.append(_check_milestone(milestone, run, unmet_dependencies=unmet_dependencies))
            break
    return results


def _check_milestone(milestone: Milestone, run: AgentRun, unmet_dependencies: list[str]) -> dict[str, Any]:
    reasons: list[str] = []
    if unmet_dependencies:
        reasons.append(f"unmet dependencies: {unmet_dependencies}")
    if milestone.required_tool and milestone.required_tool not in [call.name for call in run.tool_calls]:
        reasons.append(f"required tool {milestone.required_tool!r} was not called")
    if milestone.required_output and milestone.required_output not in run.final_output:
        reasons.append(f"required output {milestone.required_output!r} was not present")
    return {"id": milestone.id, "depends_on": milestone.depends_on, "passed": not reasons, "reasons": reasons}


def _progress_rate(milestone_results: list[dict[str, Any]]) -> float:
    if not milestone_results:
        return 0.0
    return sum(result["passed"] for result in milestone_results) / len(milestone_results)


def _failure_type(checks: list[tuple[str, bool, str | None]]) -> str | None:
    failed = [name for name, passed, _ in checks if not passed]
    if not failed:
        return None
    if "reference_trajectory" in failed:
        return "trajectory_mismatch"
    if "required_tools" in failed:
        return "missing_tool"
    if "forbidden_tools" in failed:
        return "forbidden_tool"
    if "milestones" in failed:
        return "milestone_not_reached"
    if "max_tool_calls" in failed:
        return "too_many_tool_calls"
    if "max_latency_ms" in failed:
        return "latency_overrun"
    return "trajectory_failure"
