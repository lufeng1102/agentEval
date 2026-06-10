from __future__ import annotations

from typing import Any

from evaluators.matching import value_matches
from schemas import AgentRun, EvalCase, EvalResult


class BrowserEvaluator:
    name = "browser"

    async def evaluate(self, case: EvalCase, run: AgentRun) -> EvalResult:
        env = run.artifacts.get("environment") or {}
        browser = env.get("browser") or []
        if not browser:
            return EvalResult(case_id=case.id, repeat_index=run.repeat_index, evaluator=self.name, score=0, passed=False, failure_type="browser_missing", failure_reason="browser artifacts are missing")

        expected = _expected_browser(case)
        violations: list[str] = []
        checks: list[bool] = []
        failed_checks = [check for check in browser if check.get("error") or check.get("status") == "error"]
        screenshots = [check for check in browser if check.get("screenshot_path")]

        if expected.get("max_browser_failures") is not None:
            max_failures = int(expected["max_browser_failures"])
            ok = len(failed_checks) <= max_failures
            checks.append(ok)
            if not ok:
                violations.append(f"browser failures {len(failed_checks)} exceeds max {max_failures}")

        for spec in expected.get("required_url", []) or []:
            ok = any(_field_matches(check.get("url") or "", spec) for check in browser)
            checks.append(ok)
            if not ok:
                violations.append(f"required browser url not matched: {_spec_label(spec)}")

        for spec in expected.get("required_title", []) or []:
            ok = any(_field_matches(check.get("title") or "", spec) for check in browser)
            checks.append(ok)
            if not ok:
                violations.append(f"required browser title not matched: {_spec_label(spec)}")

        for spec in expected.get("required_text", []) or []:
            matched = _matching_browser_checks(browser, spec)
            ok = bool(matched) and any(_field_matches(check.get("text") or "", spec) for check in matched)
            checks.append(ok)
            if not ok:
                violations.append(f"required browser text not found: {_spec_label(spec)}")

        for spec in expected.get("forbidden_text", []) or []:
            matched = _matching_browser_checks(browser, spec)
            ok = not any(_field_matches(check.get("text") or "", spec) for check in matched)
            checks.append(ok)
            if not ok:
                violations.append(f"forbidden browser text matched: {_spec_label(spec)}")

        for selector in expected.get("required_selectors", []) or []:
            ok = any(check.get("selector") == selector and not check.get("error") for check in browser)
            checks.append(ok)
            if not ok:
                violations.append(f"required browser selector not found: {selector}")

        for spec in expected.get("required_attributes", []) or []:
            matched = _matching_browser_checks(browser, spec)
            expected_value = spec.get("value")
            mode = str(spec.get("match_mode") or "exact")
            ok = bool(matched) and any(value_matches(expected_value, check.get("attribute_value"), mode) for check in matched)
            checks.append(ok)
            if not ok:
                violations.append(f"required browser attribute not matched: {_spec_label(spec)}")

        if expected.get("required_screenshots") is not None:
            minimum = int(expected["required_screenshots"])
            ok = len(screenshots) >= minimum
            checks.append(ok)
            if not ok:
                violations.append(f"browser screenshots {len(screenshots)} below required {minimum}")

        passed = not violations
        score = sum(1 for item in checks if item) / len(checks) if checks else (1.0 if passed else 0.0)
        return EvalResult(
            case_id=case.id,
            repeat_index=run.repeat_index,
            evaluator=self.name,
            score=score,
            passed=passed,
            metrics={
                "browser_checks": len(browser),
                "browser_failures": len(failed_checks),
                "screenshots": len(screenshots),
                "violations": violations,
            },
            failure_type=None if passed else "browser_violation",
            failure_reason=None if passed else "; ".join(violations),
            artifacts={"browser": browser},
        )


def _expected_browser(case: EvalCase) -> dict[str, Any]:
    direct = case.expected.get("browser") or {}
    if direct:
        return direct
    environment = case.expected.get("environment") or {}
    return environment.get("browser") or {}


def _matching_browser_checks(checks: list[dict[str, Any]], spec: Any) -> list[dict[str, Any]]:
    if isinstance(spec, str):
        return checks
    selector = spec.get("selector")
    phase = spec.get("phase")
    attribute = spec.get("attribute")
    url = spec.get("url")
    path = spec.get("path")
    return [
        check
        for check in checks
        if (selector is None or check.get("selector") == selector)
        and (phase is None or check.get("phase") == phase)
        and (attribute is None or check.get("attribute") == attribute)
        and (url is None or check.get("url") == url)
        and (path is None or str(check.get("url", "")).endswith(str(path)))
    ]


def _field_matches(actual: str, spec: Any) -> bool:
    if isinstance(spec, str):
        return spec in actual
    if "contains" in spec:
        return str(spec["contains"]) in actual
    if "value" in spec:
        return value_matches(spec.get("value"), actual, str(spec.get("match_mode") or "exact"))
    if "equals" in spec:
        return actual == str(spec["equals"])
    return False


def _spec_label(spec: Any) -> str:
    if isinstance(spec, str):
        return spec
    return str(spec.get("selector") or spec.get("contains") or spec.get("value") or spec.get("url") or spec.get("path") or spec)
