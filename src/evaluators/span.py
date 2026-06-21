from __future__ import annotations

from typing import Any

from schemas import AgentRun, EvalCase, EvalResult


class SpanEvaluator:
    name = "span"

    async def evaluate(self, case: EvalCase, run: AgentRun) -> EvalResult:
        expected = case.expected.get("spans") or {}
        if not isinstance(expected, dict):
            expected = {}
        spans = run.spans
        span_names = [span.name for span in spans]
        span_kinds = [str(span.kind) for span in spans]
        error_spans = [span for span in spans if span.error or span.status == "error"]
        checks: list[tuple[str, bool, str | None]] = []

        required_kinds = [str(item) for item in expected.get("required_kinds", [])]
        missing_kinds = [kind for kind in required_kinds if kind not in span_kinds]
        if required_kinds:
            checks.append(("required_kinds", not missing_kinds, f"missing span kinds: {missing_kinds}" if missing_kinds else None))

        required_names = [str(item) for item in expected.get("required_names", [])]
        missing_names = [name for name in required_names if name not in span_names]
        if required_names:
            checks.append(("required_names", not missing_names, f"missing span names: {missing_names}" if missing_names else None))

        forbidden_names = [str(item) for item in expected.get("forbidden_names", [])]
        forbidden_seen = [name for name in span_names if name in forbidden_names]
        if forbidden_names:
            checks.append(("forbidden_names", not forbidden_seen, f"forbidden spans observed: {forbidden_seen}" if forbidden_seen else None))

        max_error_spans = expected.get("max_error_spans")
        if max_error_spans is not None:
            checks.append(("max_error_spans", len(error_spans) <= int(max_error_spans), f"error span count {len(error_spans)} exceeded {max_error_spans}" if len(error_spans) > int(max_error_spans) else None))

        max_spans = expected.get("max_spans")
        if max_spans is not None:
            checks.append(("max_spans", len(spans) <= int(max_spans), f"span count {len(spans)} exceeded {max_spans}" if len(spans) > int(max_spans) else None))

        max_latency_ms = expected.get("max_latency_ms")
        latency_ms = run.latency_ms or sum(span.latency_ms or 0 for span in spans)
        if max_latency_ms is not None:
            checks.append(("max_latency_ms", latency_ms <= float(max_latency_ms), f"latency {latency_ms:.0f}ms exceeded {float(max_latency_ms):.0f}ms" if latency_ms > float(max_latency_ms) else None))

        attribute_checks = _check_required_attributes(expected.get("required_attributes") or [], run)
        checks.extend(attribute_checks)

        if not checks:
            return EvalResult(case_id=case.id, evaluator=self.name, score=0, passed=False, metrics=_metrics(spans, latency_ms, checks), failure_reason="no span expectations configured")

        passed_count = sum(passed for _, passed, _ in checks)
        failures = [reason for _, passed, reason in checks if not passed and reason]
        return EvalResult(
            case_id=case.id,
            evaluator=self.name,
            score=passed_count / len(checks),
            passed=passed_count == len(checks),
            metrics=_metrics(spans, latency_ms, checks),
            failure_reason="; ".join(failures) if failures else None,
            failure_type="span_contract" if failures else None,
        )


def _check_required_attributes(requirements: list[dict[str, Any]], run: AgentRun) -> list[tuple[str, bool, str | None]]:
    checks = []
    for requirement in requirements:
        key = str(requirement.get("key") or "")
        expected_value = requirement.get("value")
        match_mode = str(requirement.get("match_mode") or "exact")
        matched = False
        for span in run.spans:
            if key not in span.attributes:
                continue
            actual = span.attributes.get(key)
            if match_mode == "contains":
                matched = str(expected_value) in str(actual)
            else:
                matched = actual == expected_value
            if matched:
                break
        checks.append((f"required_attribute:{key}", matched, f"required attribute {key}={expected_value!r} not found" if not matched else None))
    return checks


def _metrics(spans, latency_ms: float, checks: list[tuple[str, bool, str | None]]) -> dict[str, Any]:
    return {
        "span_count": len(spans),
        "error_spans": sum(1 for span in spans if span.error or span.status == "error"),
        "span_kinds": [str(span.kind) for span in spans],
        "span_names": [span.name for span in spans],
        "tool_span_count": sum(1 for span in spans if span.kind == "tool"),
        "latency_ms": latency_ms,
        "checks": [{"name": name, "passed": passed, "reason": reason} for name, passed, reason in checks],
    }
