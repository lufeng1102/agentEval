from __future__ import annotations

import re
from typing import Any

from schemas import AgentRun, EvalCase, EvalResult


class RegexEvaluator:
    name = "regex"

    async def evaluate(self, case: EvalCase, run: AgentRun) -> EvalResult:
        spec = _normalize_regex_spec(case.expected.get("regex"))
        if not spec["include"] and not spec["exclude"]:
            return EvalResult(
                case_id=case.id,
                evaluator=self.name,
                score=0,
                passed=False,
                failure_reason="expected.regex is not configured",
            )

        flags = _compile_flags(spec["flags"])
        missing = [pattern for pattern in spec["include"] if re.search(pattern, run.final_output, flags) is None]
        present_forbidden = [pattern for pattern in spec["exclude"] if re.search(pattern, run.final_output, flags) is not None]
        passed = not missing and not present_forbidden
        total_checks = len(spec["include"]) + len(spec["exclude"])
        failed_checks = len(missing) + len(present_forbidden)

        return EvalResult(
            case_id=case.id,
            evaluator=self.name,
            score=(total_checks - failed_checks) / total_checks if total_checks else 0,
            passed=passed,
            metrics={
                "include": spec["include"],
                "exclude": spec["exclude"],
                "flags": spec["flags"],
                "missing": missing,
                "present_forbidden": present_forbidden,
            },
            failure_reason=_failure_reason(missing, present_forbidden),
        )


def _normalize_regex_spec(raw: Any) -> dict[str, list[str]]:
    if raw is None:
        return {"include": [], "exclude": [], "flags": []}
    if isinstance(raw, str):
        return {"include": [raw], "exclude": [], "flags": []}
    if isinstance(raw, list):
        return {"include": [str(item) for item in raw], "exclude": [], "flags": []}
    if isinstance(raw, dict):
        include = raw.get("include", [])
        exclude = raw.get("exclude", [])
        flags = raw.get("flags", [])
        if isinstance(include, str):
            include = [include]
        if isinstance(exclude, str):
            exclude = [exclude]
        if isinstance(flags, str):
            flags = [flags]
        return {"include": [str(item) for item in include], "exclude": [str(item) for item in exclude], "flags": [str(item).lower() for item in flags]}
    return {"include": [str(raw)], "exclude": [], "flags": []}


def _compile_flags(names: list[str]) -> int:
    flags = 0
    for name in names:
        if name == "ignorecase":
            flags |= re.IGNORECASE
        elif name == "multiline":
            flags |= re.MULTILINE
        elif name == "dotall":
            flags |= re.DOTALL
    return flags


def _failure_reason(missing: list[str], present_forbidden: list[str]) -> str | None:
    reasons: list[str] = []
    if missing:
        reasons.append(f"missing regex matches: {missing}")
    if present_forbidden:
        reasons.append(f"forbidden regex matched: {present_forbidden}")
    return "; ".join(reasons) if reasons else None
