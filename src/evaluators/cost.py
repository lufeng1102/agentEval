from __future__ import annotations

from config import EvaluatorConfig
from schemas import AgentRun, EvalCase, EvalResult


class CostEvaluator:
    name = "cost"

    def __init__(self, config: EvaluatorConfig | None = None):
        self.config = config or EvaluatorConfig(type="cost")

    async def evaluate(self, case: EvalCase, run: AgentRun) -> EvalResult:
        expected = case.expected
        checks: list[tuple[str, bool, str | None]] = []
        usage = run.usage
        total_input_tokens = usage.total_input_tokens
        total_tokens = total_input_tokens + usage.output_tokens
        cache_miss_tokens = usage.input_tokens + usage.cache_creation_input_tokens
        estimated_cost = self._estimated_cost(run)

        _add_max_check(checks, "max_latency_ms", run.latency_ms, expected.get("max_latency_ms"), unit="ms")
        _add_max_check(checks, "max_input_tokens", total_input_tokens, expected.get("max_input_tokens"))
        _add_max_check(checks, "max_output_tokens", usage.output_tokens, expected.get("max_output_tokens"))
        _add_max_check(checks, "max_total_tokens", total_tokens, expected.get("max_total_tokens"))
        _add_max_check(checks, "max_cache_miss_tokens", cache_miss_tokens, expected.get("max_cache_miss_tokens"))
        _add_max_check(checks, "max_estimated_cost_usd", estimated_cost, expected.get("max_estimated_cost_usd"), unit="usd")

        if not checks:
            return EvalResult(
                case_id=case.id,
                evaluator=self.name,
                score=0,
                passed=False,
                metrics=_metrics(run, total_input_tokens, total_tokens, cache_miss_tokens, estimated_cost),
                failure_reason="no cost expectations configured",
            )

        passed_count = sum(passed for _, passed, _ in checks)
        failures = [reason for _, passed, reason in checks if not passed and reason]
        return EvalResult(
            case_id=case.id,
            evaluator=self.name,
            score=passed_count / len(checks),
            passed=not failures,
            metrics={**_metrics(run, total_input_tokens, total_tokens, cache_miss_tokens, estimated_cost), "checks": [{"name": name, "passed": passed, "reason": reason} for name, passed, reason in checks]},
            failure_reason="; ".join(failures) if failures else None,
        )

    def _estimated_cost(self, run: AgentRun) -> float:
        settings = self.config.settings
        input_rate = float(settings.get("input_cost_per_million", 0))
        output_rate = float(settings.get("output_cost_per_million", 0))
        cache_write_rate = float(settings.get("cache_write_cost_per_million", input_rate * 1.25 if input_rate else 0))
        cache_read_rate = float(settings.get("cache_read_cost_per_million", input_rate * 0.1 if input_rate else 0))
        return (
            run.usage.input_tokens * input_rate
            + run.usage.output_tokens * output_rate
            + run.usage.cache_creation_input_tokens * cache_write_rate
            + run.usage.cache_read_input_tokens * cache_read_rate
        ) / 1_000_000


def _add_max_check(checks: list[tuple[str, bool, str | None]], name: str, actual: float, limit: object, unit: str = "") -> None:
    if limit is None:
        return
    maximum = float(limit)
    passed = actual <= maximum
    suffix = f" {unit}" if unit else ""
    reason = None if passed else f"{name} exceeded: actual {actual:.6g}{suffix}, max {maximum:.6g}{suffix}"
    checks.append((name, passed, reason))


def _metrics(run: AgentRun, total_input_tokens: int, total_tokens: int, cache_miss_tokens: int, estimated_cost: float) -> dict:
    return {
        "latency_ms": run.latency_ms,
        "input_tokens": run.usage.input_tokens,
        "output_tokens": run.usage.output_tokens,
        "cache_creation_input_tokens": run.usage.cache_creation_input_tokens,
        "cache_read_input_tokens": run.usage.cache_read_input_tokens,
        "total_input_tokens": total_input_tokens,
        "total_tokens": total_tokens,
        "cache_miss_tokens": cache_miss_tokens,
        "estimated_cost_usd": estimated_cost,
    }
