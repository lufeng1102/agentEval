from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from config import EvaluatorConfig
from schemas import AgentRun, EvalCase, EvalResult, Usage


JUDGE_METRIC_TYPES = {
    "answer_relevancy",
    "faithfulness",
    "context_relevancy",
    "context_precision",
    "context_recall",
    "task_completion",
    "hallucination",
    "conversation_quality",
}

CONTEXT_DEPENDENT_METRICS = {
    "faithfulness",
    "context_relevancy",
    "context_precision",
    "context_recall",
    "hallucination",
}

DEFAULT_FAILURE_TYPES = {
    "answer_relevancy": "irrelevant_answer",
    "faithfulness": "unfaithful_answer",
    "context_relevancy": "irrelevant_context",
    "context_precision": "low_context_precision",
    "context_recall": "low_context_recall",
    "task_completion": "task_incomplete",
    "hallucination": "hallucination",
    "conversation_quality": "conversation_quality_failure",
}


class JudgeMetricVerdict(BaseModel):
    score: float = Field(ge=0, le=1)
    passed: bool | None = None
    reason: str = ""
    failure_type: str | None = None
    metrics: dict[str, Any] = Field(default_factory=dict)


class JudgeMetricEvaluator:
    def __init__(self, config: EvaluatorConfig, metric_name: str):
        self.config = config
        self.name = metric_name

    async def evaluate(self, case: EvalCase, run: AgentRun) -> EvalResult:
        context = get_retrieval_context(case, run, self.config.settings.get("context_source", "auto"))
        if self.name in CONTEXT_DEPENDENT_METRICS and not context and not self.config.settings.get("allow_empty_context", False):
            return EvalResult(case_id=case.id, evaluator=self.name, score=0, passed=False, failure_reason="metric requires retrieval or expected context", failure_type="missing_context")

        mock = _mock_judgement(case, self.name) or self.config.settings.get("mock_judgement")
        usage: dict[str, Any] = {}
        if mock is not None:
            verdict = _parse_verdict(mock)
        else:
            cached = _read_metric_cache(case, run, self.name, self.config)
            if cached is not None:
                verdict = _parse_verdict(cached.get("verdict", cached))
                usage = cached.get("usage", {})
            else:
                verdict, usage = await self._judge_with_anthropic(case, run)
                _write_metric_cache(case, run, self.name, self.config, {"verdict": verdict.model_dump(), "usage": usage})

        score = max(0.0, min(1.0, float(verdict.score)))
        passed = bool(verdict.passed if verdict.passed is not None else score >= self.config.threshold)
        metrics = dict(verdict.metrics)
        if usage:
            metrics["judge_usage"] = usage
        metrics.setdefault("threshold", self.config.threshold)
        metrics.setdefault("context_count", len(context))
        return EvalResult(
            case_id=case.id,
            evaluator=self.name,
            score=score,
            passed=passed,
            judgements=[verdict.model_dump(mode="json")],
            metrics=metrics,
            failure_reason=None if passed else verdict.reason or f"{self.name} judge failed the case",
            failure_type=None if passed else verdict.failure_type or DEFAULT_FAILURE_TYPES.get(self.name, "judge_metric_failure"),
        )

    async def _judge_with_anthropic(self, case: EvalCase, run: AgentRun) -> tuple[JudgeMetricVerdict, dict[str, Any]]:
        try:
            import anthropic
        except ModuleNotFoundError:
            return JudgeMetricVerdict(score=0, passed=False, reason="anthropic package is not installed", failure_type="judge_api_error"), {}

        client = anthropic.AsyncAnthropic()
        prompt = _build_metric_prompt(self.name, case, run, self.config.settings)
        try:
            response = await client.messages.create(
                model=self.config.judge_model,
                max_tokens=int(self.config.settings.get("max_output_tokens", 16000)),
                thinking={"type": "adaptive"},
                output_config={"effort": self.config.settings.get("effort", "high")},
                cache_control={"type": "ephemeral"},
                system="You are a strict evaluator. Return only JSON with keys score, passed, reason, failure_type, metrics.",
                messages=[{"role": "user", "content": prompt}],
            )
        except anthropic.APIError as exc:
            return JudgeMetricVerdict(score=0, passed=False, reason=f"judge API error: {exc}", failure_type="judge_api_error"), {}
        text = _extract_text(response.content)
        return _parse_verdict(text), _usage_dict(response)


def get_retrieval_context(case: EvalCase, run: AgentRun, source: str = "auto") -> list[str]:
    sources = [source] if source != "auto" else ["expected.retrieval_context", "expected.expected_context", "run.artifacts.retrieval_context", "run.artifacts.context"]
    for item in sources:
        if item == "expected.retrieval_context":
            values = _as_list(case.expected.get("retrieval_context"))
        elif item == "expected.expected_context":
            values = _as_list(case.expected.get("expected_context"))
        elif item == "run.artifacts.retrieval_context":
            values = _as_list(run.artifacts.get("retrieval_context"))
        elif item == "run.artifacts.context":
            values = _as_list(run.artifacts.get("context"))
        else:
            values = []
        if values:
            return values
    return []


def get_expected_context(case: EvalCase) -> list[str]:
    return _as_list(case.expected.get("expected_context"))


def get_required_facts(case: EvalCase) -> list[str]:
    return _as_list(case.expected.get("required_facts"))


def truncate_payload(payload: Any, max_chars: int) -> Any:
    if isinstance(payload, dict):
        return {key: truncate_payload(value, max_chars) for key, value in payload.items()}
    if isinstance(payload, list):
        return [truncate_payload(item, max_chars) for item in payload]
    if isinstance(payload, str) and len(payload) > max_chars:
        return payload[:max_chars] + "...[truncated]"
    return payload


def sanitize_metric_payload(payload: Any, max_chars: int = 12000, key: str = "") -> Any:
    sensitive = ["api_key", "apikey", "token", "secret", "password", "authorization", "cookie", "credential", "private_key", "access_key", "refresh_token", "session", "bearer"]
    if any(part in key.lower() for part in sensitive):
        return "[REDACTED]"
    if isinstance(payload, dict):
        return {str(k): sanitize_metric_payload(v, max_chars, str(k)) for k, v in payload.items()}
    if isinstance(payload, list):
        return [sanitize_metric_payload(item, max_chars, key) for item in payload]
    if isinstance(payload, str) and len(payload) > max_chars:
        return payload[:max_chars] + "...[truncated]"
    return payload


def _build_metric_prompt(metric_name: str, case: EvalCase, run: AgentRun, settings: dict[str, Any]) -> str:
    max_chars = int(settings.get("max_context_chars", 12000))
    context = {
        "metric": metric_name,
        "definition": _metric_definition(metric_name),
        "scoring": "Return score from 0 to 1. Use 1 for fully satisfying the metric and 0 for complete failure.",
        "case_id": case.id,
        "input": case.input if isinstance(case.input, str) else [message.model_dump(mode="json") for message in case.input],
        "expected": case.expected,
        "agent_output": run.final_output,
        "messages": [message.model_dump(mode="json") for message in run.messages],
        "tool_calls": [call.model_dump(mode="json") for call in run.tool_calls],
        "retrieval_context": get_retrieval_context(case, run, settings.get("context_source", "auto")),
        "instruction": "Return strict JSON only with keys: score, passed, reason, failure_type, metrics.",
    }
    sanitized = sanitize_metric_payload(truncate_payload(context, max_chars), max_chars)
    return json.dumps(sanitized, ensure_ascii=False, sort_keys=True)


def _parse_verdict(payload: str | dict[str, Any] | JudgeMetricVerdict) -> JudgeMetricVerdict:
    if isinstance(payload, JudgeMetricVerdict):
        return payload
    if isinstance(payload, str):
        try:
            data = json.loads(payload)
        except json.JSONDecodeError:
            start = payload.find("{")
            end = payload.rfind("}")
            if start >= 0 and end > start:
                try:
                    data = json.loads(payload[start : end + 1])
                except json.JSONDecodeError:
                    data = {"score": 0, "passed": False, "reason": "judge returned non-JSON output", "metrics": {"raw": payload}}
            else:
                data = {"score": 0, "passed": False, "reason": "judge returned non-JSON output", "metrics": {"raw": payload}}
    else:
        data = dict(payload)
    data.setdefault("metrics", {})
    data.setdefault("reason", "")
    return JudgeMetricVerdict.model_validate(data)


def _mock_judgement(case: EvalCase, metric_name: str) -> dict[str, Any] | None:
    metrics = case.expected.get("judge_metrics") if isinstance(case.expected.get("judge_metrics"), dict) else {}
    item = metrics.get(metric_name) if isinstance(metrics, dict) else None
    return dict(item) if isinstance(item, dict) else None


def _metric_definition(metric_name: str) -> str:
    return {
        "answer_relevancy": "Evaluate whether the answer directly addresses the user's input.",
        "faithfulness": "Evaluate whether the answer's factual claims are supported by the provided context.",
        "context_relevancy": "Evaluate whether retrieved context is relevant to the user's input.",
        "context_precision": "Evaluate what fraction of retrieved context is useful for answering the input.",
        "context_recall": "Evaluate whether retrieved context covers required facts or expected context.",
        "task_completion": "Evaluate whether the agent completed the expected task goal and success criteria.",
        "hallucination": "Evaluate whether the answer contains unsupported or forbidden claims. Higher score means fewer hallucinations.",
        "conversation_quality": "Evaluate multi-turn conversation quality, expected behaviors, tone, and context carryover.",
    }.get(metric_name, "Evaluate the output quality for this metric.")


def _read_metric_cache(case: EvalCase, run: AgentRun, metric_name: str, config: EvaluatorConfig) -> dict[str, Any] | None:
    if not config.settings.get("cache", False):
        return None
    path = _metric_cache_path(case, run, metric_name, config)
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def _write_metric_cache(case: EvalCase, run: AgentRun, metric_name: str, config: EvaluatorConfig, payload: dict[str, Any]) -> None:
    if not config.settings.get("cache", False):
        return
    path = _metric_cache_path(case, run, metric_name, config)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _metric_cache_path(case: EvalCase, run: AgentRun, metric_name: str, config: EvaluatorConfig) -> Path:
    cache_dir = Path(config.settings.get("cache_dir", ".agenteval/metric-cache"))
    payload = {
        "metric": metric_name,
        "case_id": case.id,
        "input": case.input if isinstance(case.input, str) else [message.model_dump(mode="json") for message in case.input],
        "expected": case.expected,
        "final_output": run.final_output,
        "messages": [message.model_dump(mode="json") for message in run.messages],
        "tool_calls": [call.model_dump(mode="json") for call in run.tool_calls],
        "artifacts": run.artifacts,
        "threshold": config.threshold,
        "settings": {key: value for key, value in config.settings.items() if key not in {"mock_judgement"}},
    }
    digest = hashlib.sha256(json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str).encode("utf-8")).hexdigest()
    return cache_dir / f"{digest}.json"


def _as_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, list):
        return [str(item) for item in value if item is not None]
    return [str(value)]


def _extract_text(content: list[Any]) -> str:
    return "".join(getattr(block, "text", "") for block in content if getattr(block, "type", None) == "text").strip()


def _usage_dict(response: Any) -> dict[str, int]:
    usage = getattr(response, "usage", None)
    if usage is None:
        return Usage().model_dump()
    return Usage(
        input_tokens=getattr(usage, "input_tokens", 0) or 0,
        output_tokens=getattr(usage, "output_tokens", 0) or 0,
        cache_creation_input_tokens=getattr(usage, "cache_creation_input_tokens", 0) or 0,
        cache_read_input_tokens=getattr(usage, "cache_read_input_tokens", 0) or 0,
    ).model_dump()
