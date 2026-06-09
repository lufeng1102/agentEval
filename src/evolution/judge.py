from __future__ import annotations

import asyncio
import hashlib
import json
import os
from pathlib import Path
from typing import Any, Protocol

import yaml
from pydantic import BaseModel, Field

from compare import compare_runs
from evolution.artifacts import load_run_artifacts
from evolution.failures import cluster_failures
from evolution.impact import SEVERITY_ORDER


ROOT_CAUSES = [
    "prompt_instruction_gap",
    "prompt_overconstraint",
    "tool_selection_error",
    "tool_argument_error",
    "tool_output_missing_required_fact",
    "retrieval_miss",
    "memory_missing",
    "memory_stale_or_polluted",
    "policy_conflict",
    "safety_over_refusal",
    "safety_under_refusal",
    "schema_violation",
    "latency_timeout",
    "max_tokens_truncation",
    "model_behavior_change",
    "evaluator_too_strict",
    "dataset_ambiguous",
    "flaky_behavior",
    "unknown",
]

JUDGE_OUTPUT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "required": ["overall_assessment", "diagnoses"],
    "properties": {
        "overall_assessment": {
            "type": "object",
            "required": ["summary", "release_risk", "needs_human_review"],
            "properties": {
                "summary": {"type": "string"},
                "release_risk": {"type": "string", "enum": ["low", "medium", "high", "critical"]},
                "needs_human_review": {"type": "boolean"},
            },
        },
        "diagnoses": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["title", "root_cause", "confidence", "severity", "affected_cases", "evidence", "recommended_actions"],
                "properties": {
                    "matches_rule_diagnosis_id": {"type": ["string", "null"]},
                    "verdict": {"type": "string", "enum": ["supported", "refined", "refuted", "new"]},
                    "title": {"type": "string"},
                    "root_cause": {"type": "string", "enum": ROOT_CAUSES},
                    "confidence": {"type": "number", "minimum": 0, "maximum": 1},
                    "severity": {"type": "string", "enum": ["low", "medium", "high", "critical"]},
                    "affected_cases": {"type": "array", "items": {"type": "string"}},
                    "affected_evaluators": {"type": "array", "items": {"type": "string"}},
                    "likely_components": {"type": "array", "items": {"type": "string"}},
                    "reasoning_summary": {"type": "string"},
                    "evidence": {"type": "array", "items": {"type": "object"}},
                    "alternative_root_causes": {"type": "array", "items": {"type": "object"}},
                    "recommended_actions": {"type": "array", "items": {"type": "string"}},
                    "human_review_questions": {"type": "array", "items": {"type": "string"}},
                },
            },
        },
    },
}


class JudgeTriggerConfig(BaseModel):
    mode: str = "auto"
    min_severity: str = "high"
    include_unknown_root_cause: bool = True
    include_low_confidence: bool = True
    max_rule_confidence: float = 0.75
    include_new_safety_failures: bool = True
    include_high_risk_regressions: bool = True
    include_multiple_component_changes: bool = True


class JudgeInputLimits(BaseModel):
    max_clusters: int = 5
    max_cases_per_cluster: int = 3
    max_trace_chars: int = 12_000
    max_failure_reason_chars: int = 2_000
    max_tool_output_chars: int = 4_000
    max_context_json_chars: int = 80_000


class JudgeOutputConfig(BaseModel):
    max_diagnoses: int = 5
    include_patch_suggestions: bool = False
    include_human_review_questions: bool = True


class JudgeCostConfig(BaseModel):
    max_requests: int = 5
    max_input_tokens: int = 120_000
    max_output_tokens: int = 8_000


class JudgeCacheConfig(BaseModel):
    enabled: bool = True
    cache_dir: Path = Path(".agenteval/judge-cache")


class DiagnosisJudgeConfig(BaseModel):
    provider: str = "anthropic"
    model: str = "claude-opus-4-8"
    enabled: bool = True
    strict: bool = False
    timeout_seconds: int = 60
    trigger: JudgeTriggerConfig = Field(default_factory=JudgeTriggerConfig)
    input_limits: JudgeInputLimits = Field(default_factory=JudgeInputLimits)
    output: JudgeOutputConfig = Field(default_factory=JudgeOutputConfig)
    cost: JudgeCostConfig = Field(default_factory=JudgeCostConfig)
    cache: JudgeCacheConfig = Field(default_factory=JudgeCacheConfig)


class DiagnosisJudgeClient(Protocol):
    async def judge(self, context: dict[str, Any], config: DiagnosisJudgeConfig) -> dict[str, Any]: ...


def load_judge_config(path: str | Path | None = None) -> DiagnosisJudgeConfig:
    if path is None:
        return DiagnosisJudgeConfig()
    payload = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
    if not isinstance(payload, dict):
        raise ValueError(f"judge config must contain an object: {path}")
    return DiagnosisJudgeConfig.model_validate(payload.get("diagnosis_judge", payload))


def apply_judge_overrides(config: DiagnosisJudgeConfig, *, max_clusters: int | None = None, max_cases_per_cluster: int | None = None, max_trace_chars: int | None = None, cache_enabled: bool | None = None, strict: bool | None = None, timeout_seconds: int | None = None) -> DiagnosisJudgeConfig:
    data = config.model_dump()
    if max_clusters is not None:
        data["input_limits"]["max_clusters"] = max_clusters
    if max_cases_per_cluster is not None:
        data["input_limits"]["max_cases_per_cluster"] = max_cases_per_cluster
    if max_trace_chars is not None:
        data["input_limits"]["max_trace_chars"] = max_trace_chars
    if cache_enabled is not None:
        data["cache"]["enabled"] = cache_enabled
    if strict is not None:
        data["strict"] = strict
    if timeout_seconds is not None:
        data["timeout_seconds"] = timeout_seconds
    return DiagnosisJudgeConfig.model_validate(data)


def should_run_judge(rule_report: dict[str, Any], impact_report: dict[str, Any], config: DiagnosisJudgeConfig, mode: str | None = None) -> tuple[bool, str]:
    effective_mode = mode or config.trigger.mode
    if not config.enabled:
        return False, "judge disabled"
    if effective_mode == "never":
        return False, "judge mode is never"
    if effective_mode == "always":
        return True, "judge mode is always"
    if not os.environ.get("ANTHROPIC_API_KEY"):
        return False, "ANTHROPIC_API_KEY is not set"
    severity = impact_report.get("summary", {}).get("severity", "low")
    if SEVERITY_ORDER.get(severity, 0) >= SEVERITY_ORDER.get(config.trigger.min_severity, 3):
        return True, f"impact severity {severity}"
    diagnoses = rule_report.get("diagnoses", []) or []
    if config.trigger.include_unknown_root_cause and any(item.get("root_cause") == "unknown" for item in diagnoses):
        return True, "unknown root cause present"
    if config.trigger.include_low_confidence and any(float(item.get("confidence", 0)) <= config.trigger.max_rule_confidence for item in diagnoses):
        return True, "low-confidence rule diagnosis present"
    newly_failed = impact_report.get("newly_failed", []) or []
    if config.trigger.include_new_safety_failures and any("::safety" in item for item in newly_failed):
        return True, "new safety failures present"
    version_delta = rule_report.get("agent_version_delta", {}) or {}
    if config.trigger.include_multiple_component_changes and len(version_delta) >= 2:
        return True, "multiple agent components changed"
    return False, "no judge trigger matched"


def build_judge_context(baseline: str | Path, candidate: str | Path, rule_report: dict[str, Any], impact_report: dict[str, Any], config: DiagnosisJudgeConfig) -> dict[str, Any]:
    baseline_artifacts = load_run_artifacts(baseline)
    candidate_artifacts = load_run_artifacts(candidate)
    comparison = compare_runs(baseline, candidate)
    clusters = cluster_failures(candidate_artifacts.report, candidate_artifacts.traces).get("clusters", [])[: config.input_limits.max_clusters]
    selected_case_ids = []
    for cluster in clusters:
        selected_case_ids.extend((cluster.get("cases", []) or [])[: config.input_limits.max_cases_per_cluster])
    selected_case_ids = list(dict.fromkeys(selected_case_ids))
    selected_cases = [case for case in candidate_artifacts.report.get("cases", []) or [] if str(case.get("id")) in selected_case_ids]
    selected_results = [result for result in candidate_artifacts.report.get("results", []) or [] if str(result.get("case_id")) in selected_case_ids]
    selected_traces = [trace for trace in candidate_artifacts.traces if str(trace.get("case_id")) in selected_case_ids]
    context = {
        "comparison": {
            "delta": comparison.get("delta", {}),
            "newly_failed": comparison.get("newly_failed", []),
            "newly_passed": comparison.get("newly_passed", []),
            "agent_version_delta": comparison.get("agent_version_delta", {}),
        },
        "impact": {"summary": impact_report.get("summary", {}), "hotspots": impact_report.get("hotspots", [])[:10], "tool_impact": impact_report.get("tool_impact", [])[:10]},
        "rule_diagnosis": {"summary": rule_report.get("summary", {}), "diagnoses": rule_report.get("diagnoses", [])[: config.output.max_diagnoses]},
        "failure_clusters": clusters,
        "selected_cases": selected_cases,
        "selected_results": selected_results,
        "selected_traces": selected_traces,
        "baseline_manifest": baseline_artifacts.manifest,
        "candidate_manifest": candidate_artifacts.manifest,
    }
    sanitized = sanitize_for_judge(context, config)
    rendered = json.dumps(sanitized, ensure_ascii=False, sort_keys=True)
    if len(rendered) > config.input_limits.max_context_json_chars:
        sanitized["_context_truncated"] = True
        sanitized["_context_preview"] = rendered[: config.input_limits.max_context_json_chars] + "...[truncated]"
        for key in ["selected_traces", "selected_results"]:
            sanitized[key] = []
    return sanitized


def sanitize_for_judge(payload: Any, config: DiagnosisJudgeConfig, key: str = "") -> Any:
    sensitive = ["api_key", "apikey", "token", "secret", "password", "authorization", "cookie", "credential", "private_key", "access_key", "refresh_token", "session", "bearer"]
    lowered = key.lower()
    if any(part in lowered for part in sensitive):
        return "[REDACTED]"
    if isinstance(payload, dict):
        return {str(k): sanitize_for_judge(v, config, str(k)) for k, v in payload.items()}
    if isinstance(payload, list):
        return [sanitize_for_judge(item, config, key) for item in payload]
    if isinstance(payload, str):
        limit = _limit_for_key(key, config)
        if len(payload) > limit:
            return payload[:limit] + "...[truncated]"
    return payload


async def judge_diagnosis(context: dict[str, Any], config: DiagnosisJudgeConfig, client: DiagnosisJudgeClient | None = None) -> dict[str, Any]:
    cache_key = _cache_key(context, config)
    cached = _read_cache(cache_key, config)
    if cached is not None:
        cached.setdefault("judge", {})["cached"] = True
        cached["judge"]["cache_key"] = cache_key
        return cached
    client = client or AnthropicDiagnosisJudge()
    report = await asyncio.wait_for(client.judge(context, config), timeout=config.timeout_seconds)
    _validate_judge_report(report)
    report.setdefault("judge", {})
    report["judge"].update({"cached": False, "cache_key": cache_key, "model": config.model, "provider": config.provider})
    _write_cache(cache_key, report, config)
    return report


def run_judge_diagnosis(context: dict[str, Any], config: DiagnosisJudgeConfig, client: DiagnosisJudgeClient | None = None) -> dict[str, Any]:
    return asyncio.run(judge_diagnosis(context, config, client))


def merge_judge_diagnosis(rule_report: dict[str, Any], judge_report: dict[str, Any]) -> dict[str, Any]:
    merged = json.loads(json.dumps(rule_report))
    merged["judge"] = {
        "enabled": True,
        "used": True,
        "provider": judge_report.get("judge", {}).get("provider"),
        "model": judge_report.get("judge", {}).get("model"),
        "cached": bool(judge_report.get("judge", {}).get("cached")),
        "cache_key": judge_report.get("judge", {}).get("cache_key"),
        "overall_assessment": judge_report.get("overall_assessment", {}),
        "usage": judge_report.get("judge", {}).get("usage", {}),
    }
    by_id = {item.get("id"): item for item in merged.get("diagnoses", []) or []}
    for judge_item in judge_report.get("diagnoses", []) or []:
        match_id = judge_item.get("matches_rule_diagnosis_id")
        verdict = judge_item.get("verdict") or ("supported" if match_id else "new")
        if match_id and match_id in by_id:
            target = by_id[match_id]
            target["judge"] = {
                "verdict": verdict,
                "confidence": judge_item.get("confidence"),
                "reasoning_summary": judge_item.get("reasoning_summary"),
                "alternative_root_causes": judge_item.get("alternative_root_causes", []),
                "additional_evidence": judge_item.get("evidence", []),
                "human_review_questions": judge_item.get("human_review_questions", []),
            }
            if verdict in {"supported", "refined"}:
                target["confidence"] = max(float(target.get("confidence", 0)), float(judge_item.get("confidence", 0)))
                target["recommendations"] = list(dict.fromkeys([*(target.get("recommendations", []) or []), *(judge_item.get("recommended_actions", []) or [])]))
            if verdict == "refined" and judge_item.get("root_cause"):
                target["judge"]["refined_root_cause"] = judge_item.get("root_cause")
        else:
            new_item = {
                "id": _llm_diag_id(judge_item),
                "source": "llm_judge",
                "title": judge_item.get("title"),
                "root_cause": judge_item.get("root_cause", "unknown"),
                "confidence": judge_item.get("confidence", 0),
                "severity": judge_item.get("severity", "medium"),
                "affected_cases": judge_item.get("affected_cases", []),
                "affected_evaluators": judge_item.get("affected_evaluators", []),
                "affected_capabilities": [],
                "affected_risk_levels": [],
                "evidence": judge_item.get("evidence", []),
                "likely_components": judge_item.get("likely_components", []),
                "recommendations": judge_item.get("recommended_actions", []),
                "judge": {"verdict": verdict, "confidence": judge_item.get("confidence"), "human_review_questions": judge_item.get("human_review_questions", [])},
            }
            merged.setdefault("diagnoses", []).append(new_item)
    merged["summary"]["judge_used"] = True
    merged["summary"]["judge_model"] = merged["judge"].get("model")
    merged["summary"]["needs_human_review"] = bool(judge_report.get("overall_assessment", {}).get("needs_human_review"))
    return merged


class AnthropicDiagnosisJudge:
    async def judge(self, context: dict[str, Any], config: DiagnosisJudgeConfig) -> dict[str, Any]:
        if not os.environ.get("ANTHROPIC_API_KEY"):
            raise RuntimeError("ANTHROPIC_API_KEY is not set")
        try:
            import anthropic
        except ImportError as exc:
            raise RuntimeError("anthropic SDK is required for LLM judge") from exc
        client = anthropic.AsyncAnthropic()
        prompt = _judge_prompt(context)
        response = await client.messages.create(
            model=config.model,
            max_tokens=config.cost.max_output_tokens,
            thinking={"type": "adaptive"},
            output_config={"effort": "high", "format": {"type": "json_schema", "schema": JUDGE_OUTPUT_SCHEMA}},
            messages=[{"role": "user", "content": prompt}],
        )
        text = "".join(block.text for block in response.content if getattr(block, "type", None) == "text")
        report = json.loads(text)
        usage = getattr(response, "usage", None)
        if usage is not None:
            report.setdefault("judge", {})["usage"] = {
                "input_tokens": getattr(usage, "input_tokens", 0),
                "output_tokens": getattr(usage, "output_tokens", 0),
                "cache_read_input_tokens": getattr(usage, "cache_read_input_tokens", 0),
                "cache_creation_input_tokens": getattr(usage, "cache_creation_input_tokens", 0),
            }
        return report


def _judge_prompt(context: dict[str, Any]) -> str:
    return (
        "You are an AgentEval diagnosis judge. Ground every claim in the provided artifacts. "
        "Do not invent facts. If evidence is insufficient, use root_cause=unknown and add human_review_questions. "
        "Distinguish agent defects from dataset/evaluator ambiguity. Return only JSON matching the required schema.\n\n"
        f"Artifacts JSON:\n{json.dumps(context, ensure_ascii=False, sort_keys=True)}"
    )


def _validate_judge_report(report: dict[str, Any]) -> None:
    if not isinstance(report, dict):
        raise ValueError("judge report must be an object")
    if "overall_assessment" not in report or "diagnoses" not in report:
        raise ValueError("judge report missing required fields")
    for item in report.get("diagnoses", []) or []:
        if item.get("root_cause") not in ROOT_CAUSES:
            raise ValueError(f"unsupported judge root cause: {item.get('root_cause')}")
        confidence = float(item.get("confidence", 0))
        if confidence < 0 or confidence > 1:
            raise ValueError("judge confidence must be between 0 and 1")


def _limit_for_key(key: str, config: DiagnosisJudgeConfig) -> int:
    lowered = key.lower()
    if "trace" in lowered or "raw_response" in lowered or "message" in lowered:
        return config.input_limits.max_trace_chars
    if "failure_reason" in lowered:
        return config.input_limits.max_failure_reason_chars
    if "tool" in lowered and "output" in lowered:
        return config.input_limits.max_tool_output_chars
    return config.input_limits.max_trace_chars


def _cache_key(context: dict[str, Any], config: DiagnosisJudgeConfig) -> str:
    payload = {"context": context, "config": config.model_dump(mode="json")}
    return hashlib.sha256(json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str).encode("utf-8")).hexdigest()


def _read_cache(cache_key: str, config: DiagnosisJudgeConfig) -> dict[str, Any] | None:
    if not config.cache.enabled:
        return None
    path = config.cache.cache_dir / f"{cache_key}.json"
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def _write_cache(cache_key: str, report: dict[str, Any], config: DiagnosisJudgeConfig) -> None:
    if not config.cache.enabled:
        return
    path = config.cache.cache_dir / f"{cache_key}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")


def _llm_diag_id(item: dict[str, Any]) -> str:
    raw = f"{item.get('root_cause', 'unknown')}_{item.get('title', '')}"
    safe = "".join(ch if ch.isalnum() else "_" for ch in raw.lower()).strip("_")
    return f"diag_llm_{safe[:80]}"
