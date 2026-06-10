from __future__ import annotations

import asyncio
import hashlib
import json
import os
from html import escape
from pathlib import Path
from typing import Any, Protocol

import yaml
from pydantic import BaseModel, Field

from evolution.artifacts import load_run_artifacts
from schemas import Usage

WINNERS = {"candidate", "baseline", "tie", "needs_review"}

PAIRWISE_OUTPUT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "required": ["winner", "confidence", "reasoning", "evidence", "human_review_recommended"],
    "properties": {
        "winner": {"type": "string", "enum": sorted(WINNERS)},
        "confidence": {"type": "number", "minimum": 0, "maximum": 1},
        "reasoning": {"type": "string"},
        "evidence": {"type": "array", "items": {"type": "string"}},
        "human_review_recommended": {"type": "boolean"},
    },
}


class PairwiseInputLimits(BaseModel):
    max_cases: int = 100
    max_output_chars: int = 4_000
    max_tool_calls: int = 20
    max_tool_json_chars: int = 4_000
    max_context_json_chars: int = 40_000


class PairwiseCostConfig(BaseModel):
    max_requests: int = 100
    max_output_tokens: int = 2_000


class PairwiseCacheConfig(BaseModel):
    enabled: bool = True
    cache_dir: Path = Path(".agenteval/judge-cache")


class PairwiseJudgeConfig(BaseModel):
    provider: str = "anthropic"
    model: str = "claude-opus-4-8"
    enabled: bool = True
    strict: bool = False
    timeout_seconds: int = 60
    mode: str = "never"
    threshold: float = 0.6
    score_tolerance: float = 0.05
    latency_tolerance_ms: float = 100
    input_limits: PairwiseInputLimits = Field(default_factory=PairwiseInputLimits)
    cost: PairwiseCostConfig = Field(default_factory=PairwiseCostConfig)
    cache: PairwiseCacheConfig = Field(default_factory=PairwiseCacheConfig)


class PairwiseJudgeClient(Protocol):
    async def judge(self, context: dict[str, Any], config: PairwiseJudgeConfig) -> dict[str, Any]: ...


def load_pairwise_config(path: str | Path | None = None) -> PairwiseJudgeConfig:
    if path is None:
        return PairwiseJudgeConfig()
    payload = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
    if not isinstance(payload, dict):
        raise ValueError(f"pairwise judge config must contain an object: {path}")
    return PairwiseJudgeConfig.model_validate(payload.get("pairwise_judge", payload))


def compare_pairwise(baseline: str | Path, candidate: str | Path, *, config: PairwiseJudgeConfig | None = None, judge_mode: str | None = None, client: PairwiseJudgeClient | None = None) -> dict[str, Any]:
    config = config or PairwiseJudgeConfig()
    if judge_mode is not None:
        config = PairwiseJudgeConfig.model_validate({**config.model_dump(), "mode": judge_mode})
    baseline_artifacts = load_run_artifacts(baseline)
    candidate_artifacts = load_run_artifacts(candidate)
    cases = _case_map(baseline_artifacts.report, candidate_artifacts.report)
    baseline_runs = _run_map(baseline_artifacts.traces, baseline_artifacts.report)
    candidate_runs = _run_map(candidate_artifacts.traces, candidate_artifacts.report)
    baseline_results = _results_by_case(baseline_artifacts.report.get("results", []) or [])
    candidate_results = _results_by_case(candidate_artifacts.report.get("results", []) or [])

    items = []
    judge_requests = 0
    skipped_reason = None
    for case_id in sorted(cases)[: config.input_limits.max_cases]:
        case = cases[case_id]
        baseline_side = _side_summary(case_id, baseline_runs.get(case_id), baseline_results.get(case_id, []), config)
        candidate_side = _side_summary(case_id, candidate_runs.get(case_id), candidate_results.get(case_id, []), config)
        preliminary = _deterministic_preference(baseline_side, candidate_side, config)
        item = {
            "case_id": case_id,
            "winner": preliminary["winner"],
            "confidence": preliminary["confidence"],
            "reason": preliminary["reason"],
            "case": case,
            "baseline": baseline_side,
            "candidate": candidate_side,
            "judge": {"used": False},
        }
        should_judge, reason = _should_judge(item, config)
        if should_judge:
            if not os.environ.get("ANTHROPIC_API_KEY") and client is None:
                skipped_reason = "ANTHROPIC_API_KEY is not set"
                if config.strict:
                    raise RuntimeError(skipped_reason)
            elif judge_requests >= config.cost.max_requests:
                skipped_reason = "pairwise judge max_requests reached"
            else:
                context = _judge_context(item, config)
                judgement = run_pairwise_judge(context, config, client)
                if not judgement.get("judge", {}).get("cached"):
                    judge_requests += 1
                item["judge"] = {"used": True, **judgement.get("judge", {})}
                winner = judgement.get("winner")
                if winner in WINNERS:
                    item["winner"] = winner
                    item["confidence"] = float(judgement.get("confidence", item["confidence"]))
                    item["reason"] = judgement.get("reasoning") or item["reason"]
                    item["judge"].update({"reason": judgement.get("reasoning"), "evidence": judgement.get("evidence", []), "human_review_recommended": bool(judgement.get("human_review_recommended"))})
                    if judgement.get("human_review_recommended") and winner == "tie":
                        item["winner"] = "needs_review"
        elif reason:
            item["judge"]["skipped_reason"] = reason
        items.append(item)

    summary = _summary(items)
    summary.update({"judge_mode": config.mode, "judge_used": any(item.get("judge", {}).get("used") for item in items), "judge_requests": judge_requests})
    if skipped_reason:
        summary["judge_skipped_reason"] = skipped_reason
    return {
        "baseline": str(Path(baseline)),
        "candidate": str(Path(candidate)),
        "summary": summary,
        "by_tag": _group_summary(items, "tags"),
        "by_capability": _metadata_group_summary(items, "capability"),
        "by_risk_level": _metadata_group_summary(items, "risk_level"),
        "items": items,
    }


async def pairwise_judge(context: dict[str, Any], config: PairwiseJudgeConfig, client: PairwiseJudgeClient | None = None) -> dict[str, Any]:
    cache_key = _cache_key(context, config)
    cached = _read_cache(cache_key, config)
    if cached is not None:
        cached.setdefault("judge", {})["cached"] = True
        cached["judge"]["cache_key"] = cache_key
        return cached
    client = client or AnthropicPairwiseJudge()
    report = await asyncio.wait_for(client.judge(context, config), timeout=config.timeout_seconds)
    _validate_pairwise_judgement(report)
    report.setdefault("judge", {})
    report["judge"].update({"cached": False, "cache_key": cache_key, "model": config.model, "provider": config.provider})
    _write_cache(cache_key, report, config)
    return report


def run_pairwise_judge(context: dict[str, Any], config: PairwiseJudgeConfig, client: PairwiseJudgeClient | None = None) -> dict[str, Any]:
    return asyncio.run(pairwise_judge(context, config, client))


class AnthropicPairwiseJudge:
    async def judge(self, context: dict[str, Any], config: PairwiseJudgeConfig) -> dict[str, Any]:
        if not os.environ.get("ANTHROPIC_API_KEY"):
            raise RuntimeError("ANTHROPIC_API_KEY is not set")
        try:
            import anthropic
        except ImportError as exc:
            raise RuntimeError("anthropic SDK is required for pairwise judge") from exc
        client = anthropic.AsyncAnthropic()
        response = await client.messages.create(
            model=config.model,
            max_tokens=config.cost.max_output_tokens,
            thinking={"type": "adaptive"},
            output_config={"effort": "high", "format": {"type": "json_schema", "schema": PAIRWISE_OUTPUT_SCHEMA}},
            messages=[{"role": "user", "content": _judge_prompt(context)}],
        )
        text = "".join(getattr(block, "text", "") for block in response.content if getattr(block, "type", None) == "text")
        report = json.loads(text)
        usage = getattr(response, "usage", None)
        if usage is not None:
            report.setdefault("judge", {})["usage"] = Usage(
                input_tokens=getattr(usage, "input_tokens", 0) or 0,
                output_tokens=getattr(usage, "output_tokens", 0) or 0,
                cache_creation_input_tokens=getattr(usage, "cache_creation_input_tokens", 0) or 0,
                cache_read_input_tokens=getattr(usage, "cache_read_input_tokens", 0) or 0,
            ).model_dump()
        return report


def write_pairwise_json(path: str | Path, report: dict[str, Any]) -> None:
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")


def write_pairwise_markdown(path: str | Path, report: dict[str, Any]) -> None:
    summary = report["summary"]
    lines = [
        "# AgentEval Pairwise Preference Report",
        "",
        f"- Baseline: `{report['baseline']}`",
        f"- Candidate: `{report['candidate']}`",
        f"- Judge mode: `{summary.get('judge_mode')}`; used={summary.get('judge_used')}; requests={summary.get('judge_requests', 0)}",
    ]
    if summary.get("judge_skipped_reason"):
        lines.append(f"- Judge skipped: {summary['judge_skipped_reason']}")
    lines.extend([
        "",
        "## Summary",
        "",
        "| Metric | Value |",
        "| --- | ---: |",
        f"| Cases | {summary['cases']} |",
        f"| Candidate wins | {summary['candidate_wins']} ({summary['candidate_win_rate']:.2%}) |",
        f"| Baseline wins | {summary['baseline_wins']} ({summary['baseline_win_rate']:.2%}) |",
        f"| Ties | {summary['ties']} ({summary['tie_rate']:.2%}) |",
        f"| Needs review | {summary['needs_review']} |",
        "",
        "## By Capability",
        "",
        *_group_lines(report.get("by_capability", {}), "Capability"),
        "",
        "## By Risk Level",
        "",
        *_group_lines(report.get("by_risk_level", {}), "Risk level"),
        "",
        "## Cases",
        "",
        "| Case | Winner | Confidence | Reason |",
        "| --- | --- | ---: | --- |",
    ])
    for item in report.get("items", []):
        lines.append(f"| `{item['case_id']}` | {item['winner']} | {float(item.get('confidence', 0)):.2f} | {str(item.get('reason', '')).replace('|', '/')} |")
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text("\n".join(lines) + "\n", encoding="utf-8")


def write_pairwise_html(path: str | Path, report: dict[str, Any]) -> None:
    summary = report["summary"]
    rows = "".join(
        f"<tr><td><code>{escape(item['case_id'])}</code></td><td>{escape(item['winner'])}</td><td>{float(item.get('confidence', 0)):.2f}</td><td>{escape(str(item.get('reason', '')))}</td></tr>"
        for item in report.get("items", [])
    ) or "<tr><td colspan='4'>None</td></tr>"
    html = [
        "<!doctype html><html><head><meta charset='utf-8'><title>AgentEval Pairwise Preference Report</title>",
        "<style>body{font-family:-apple-system,BlinkMacSystemFont,Segoe UI,sans-serif;margin:2rem;background:#f6f8fa;color:#182230}.cards{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:1rem}.card,section{background:white;border:1px solid #e4e7ec;border-radius:16px;padding:1rem;margin:1rem 0}table{border-collapse:collapse;width:100%}th,td{padding:.7rem;border-bottom:1px solid #e4e7ec;text-align:left}th{background:#f9fafb}code{background:#eef2ff;padding:.12rem .35rem;border-radius:6px}@media(max-width:900px){.cards{grid-template-columns:1fr 1fr}}</style>",
        "</head><body><h1>AgentEval Pairwise Preference Report</h1>",
        f"<p>Baseline: <code>{escape(report['baseline'])}</code></p>",
        f"<p>Candidate: <code>{escape(report['candidate'])}</code></p>",
        "<div class='cards'>",
        _card("Candidate wins", f"{summary['candidate_wins']} ({summary['candidate_win_rate']:.2%})"),
        _card("Baseline wins", f"{summary['baseline_wins']} ({summary['baseline_win_rate']:.2%})"),
        _card("Ties", f"{summary['ties']} ({summary['tie_rate']:.2%})"),
        _card("Needs review", summary["needs_review"]),
        "</div>",
        f"<section><h2>Cases</h2><table><tr><th>Case</th><th>Winner</th><th>Confidence</th><th>Reason</th></tr>{rows}</table></section>",
        "</body></html>",
    ]
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text("\n".join(html), encoding="utf-8")


def _case_map(baseline_report: dict[str, Any], candidate_report: dict[str, Any]) -> dict[str, dict[str, Any]]:
    cases = {}
    for case in baseline_report.get("cases", []) or []:
        if case.get("id"):
            cases[str(case["id"])] = case
    for case in candidate_report.get("cases", []) or []:
        if case.get("id"):
            cases[str(case["id"])] = {**cases.get(str(case["id"]), {}), **case}
    return cases or {str(result.get("case_id")): {"id": str(result.get("case_id"))} for result in [*(baseline_report.get("results", []) or []), *(candidate_report.get("results", []) or [])] if result.get("case_id")}


def _run_map(traces: list[dict[str, Any]], report: dict[str, Any]) -> dict[str, dict[str, Any]]:
    runs = {str(run.get("case_id")): run for run in traces if run.get("case_id")}
    for run in report.get("runs", []) or []:
        if run.get("case_id") and str(run.get("case_id")) not in runs:
            runs[str(run["case_id"])] = run
    return runs


def _results_by_case(results: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    for result in results:
        grouped.setdefault(str(result.get("case_id")), []).append(result)
    return grouped


def _side_summary(case_id: str, run: dict[str, Any] | None, results: list[dict[str, Any]], config: PairwiseJudgeConfig) -> dict[str, Any]:
    failures = [item for item in results if not item.get("passed")]
    scores = [float(item.get("score", 0) or 0) for item in results]
    errors = list((run or {}).get("errors") or [])
    tool_calls = list((run or {}).get("tool_calls") or [])[: config.input_limits.max_tool_calls]
    return {
        "case_id": case_id,
        "present": bool(run or results),
        "final_output": _truncate(str((run or {}).get("final_output") or ""), config.input_limits.max_output_chars),
        "errors": errors,
        "latency_ms": float((run or {}).get("latency_ms") or 0),
        "tool_calls": _truncate_json(tool_calls, config.input_limits.max_tool_json_chars),
        "results": results,
        "passed_results": sum(1 for item in results if item.get("passed")),
        "failed_results": len(failures),
        "all_passed": bool(results) and not failures,
        "avg_score": sum(scores) / len(scores) if scores else 0,
    }


def _deterministic_preference(baseline: dict[str, Any], candidate: dict[str, Any], config: PairwiseJudgeConfig) -> dict[str, Any]:
    if candidate["present"] and not baseline["present"]:
        return {"winner": "candidate", "confidence": 0.7, "reason": "candidate has a run/result and baseline is missing"}
    if baseline["present"] and not candidate["present"]:
        return {"winner": "baseline", "confidence": 0.7, "reason": "baseline has a run/result and candidate is missing"}
    if not baseline["present"] and not candidate["present"]:
        return {"winner": "needs_review", "confidence": 0.0, "reason": "both baseline and candidate are missing"}
    if candidate["all_passed"] != baseline["all_passed"]:
        return {"winner": "candidate" if candidate["all_passed"] else "baseline", "confidence": 0.9, "reason": "one side passed all evaluator results"}
    score_delta = candidate["avg_score"] - baseline["avg_score"]
    if abs(score_delta) > config.score_tolerance:
        return {"winner": "candidate" if score_delta > 0 else "baseline", "confidence": min(0.95, 0.6 + abs(score_delta)), "reason": f"average score delta {score_delta:.2f}"}
    failure_delta = candidate["failed_results"] - baseline["failed_results"]
    if failure_delta != 0:
        return {"winner": "candidate" if failure_delta < 0 else "baseline", "confidence": 0.75, "reason": "fewer failed evaluator results"}
    error_delta = len(candidate["errors"]) - len(baseline["errors"])
    if error_delta != 0:
        return {"winner": "candidate" if error_delta < 0 else "baseline", "confidence": 0.7, "reason": "fewer run errors"}
    latency_delta = candidate["latency_ms"] - baseline["latency_ms"]
    if baseline["latency_ms"] and candidate["latency_ms"] and abs(latency_delta) > config.latency_tolerance_ms:
        return {"winner": "candidate" if latency_delta < 0 else "baseline", "confidence": 0.6, "reason": f"latency delta {latency_delta:.0f}ms"}
    return {"winner": "tie", "confidence": 0.6, "reason": "deterministic metrics are within tolerance"}


def _should_judge(item: dict[str, Any], config: PairwiseJudgeConfig) -> tuple[bool, str | None]:
    if not config.enabled or config.mode == "never":
        return False, "judge disabled"
    if config.mode == "always":
        return True, None
    if config.mode != "auto":
        return False, f"unsupported judge mode: {config.mode}"
    case = item.get("case") or {}
    if item["winner"] in {"tie", "needs_review"} and item["baseline"].get("final_output") != item["candidate"].get("final_output"):
        return True, None
    if (case.get("metadata") or {}).get("risk_level") in {"high", "critical"}:
        return True, None
    evaluators = {result.get("evaluator") for side in [item["baseline"], item["candidate"]] for result in side.get("results", [])}
    if any("judge" in str(evaluator) for evaluator in evaluators):
        return True, None
    return False, "auto judge trigger did not match"


def _judge_context(item: dict[str, Any], config: PairwiseJudgeConfig) -> dict[str, Any]:
    context = {
        "case": item["case"],
        "baseline": item["baseline"],
        "candidate": item["candidate"],
        "preliminary_preference": {"winner": item["winner"], "confidence": item["confidence"], "reason": item["reason"]},
        "instruction": "Choose candidate, baseline, tie, or needs_review. Ground the decision in the provided case, outputs, traces, and evaluator results. Prefer actual task success over style when expected outcomes are clear.",
    }
    rendered = json.dumps(context, ensure_ascii=False, sort_keys=True)
    if len(rendered) > config.input_limits.max_context_json_chars:
        context["_context_truncated"] = True
        context["baseline"]["tool_calls"] = []
        context["candidate"]["tool_calls"] = []
    return context


def _summary(items: list[dict[str, Any]]) -> dict[str, Any]:
    total = len(items)
    candidate_wins = sum(1 for item in items if item["winner"] == "candidate")
    baseline_wins = sum(1 for item in items if item["winner"] == "baseline")
    ties = sum(1 for item in items if item["winner"] == "tie")
    needs_review = sum(1 for item in items if item["winner"] == "needs_review")
    return {
        "cases": total,
        "judged": total,
        "candidate_wins": candidate_wins,
        "baseline_wins": baseline_wins,
        "ties": ties,
        "needs_review": needs_review,
        "candidate_win_rate": candidate_wins / total if total else 0,
        "baseline_win_rate": baseline_wins / total if total else 0,
        "tie_rate": ties / total if total else 0,
        "needs_review_rate": needs_review / total if total else 0,
    }


def _group_summary(items: list[dict[str, Any]], field: str) -> dict[str, dict[str, Any]]:
    groups: dict[str, list[dict[str, Any]]] = {}
    for item in items:
        for value in item.get("case", {}).get(field, []) or []:
            groups.setdefault(str(value), []).append(item)
    return {key: _summary(value) for key, value in groups.items()}


def _metadata_group_summary(items: list[dict[str, Any]], field: str) -> dict[str, dict[str, Any]]:
    groups: dict[str, list[dict[str, Any]]] = {}
    for item in items:
        value = (item.get("case", {}).get("metadata") or {}).get(field)
        if value:
            groups.setdefault(str(value), []).append(item)
    return {key: _summary(value) for key, value in groups.items()}


def _group_lines(groups: dict[str, dict[str, Any]], label: str) -> list[str]:
    if not groups:
        return ["None"]
    lines = [f"| {label} | Cases | Candidate wins | Baseline wins | Ties | Needs review |", "| --- | ---: | ---: | ---: | ---: | ---: |"]
    for key, item in groups.items():
        lines.append(f"| `{key}` | {item['cases']} | {item['candidate_wins']} | {item['baseline_wins']} | {item['ties']} | {item['needs_review']} |")
    return lines


def _validate_pairwise_judgement(report: dict[str, Any]) -> None:
    if not isinstance(report, dict):
        raise ValueError("pairwise judge report must be an object")
    if report.get("winner") not in WINNERS:
        raise ValueError(f"unsupported pairwise winner: {report.get('winner')}")
    confidence = float(report.get("confidence", 0))
    if confidence < 0 or confidence > 1:
        raise ValueError("pairwise judge confidence must be between 0 and 1")


def _judge_prompt(context: dict[str, Any]) -> str:
    return (
        "You are an AgentEval pairwise preference judge. Compare baseline and candidate for the same task. "
        "Return only JSON matching the schema. Do not invent facts. Use needs_review when evidence is insufficient.\n\n"
        f"Pairwise context JSON:\n{json.dumps(context, ensure_ascii=False, sort_keys=True)}"
    )


def _cache_key(context: dict[str, Any], config: PairwiseJudgeConfig) -> str:
    payload = {"context": context, "config": config.model_dump(mode="json")}
    return "pairwise_" + hashlib.sha256(json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str).encode("utf-8")).hexdigest()


def _read_cache(cache_key: str, config: PairwiseJudgeConfig) -> dict[str, Any] | None:
    if not config.cache.enabled:
        return None
    path = config.cache.cache_dir / f"{cache_key}.json"
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def _write_cache(cache_key: str, report: dict[str, Any], config: PairwiseJudgeConfig) -> None:
    if not config.cache.enabled:
        return
    path = config.cache.cache_dir / f"{cache_key}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")


def _truncate(value: str, max_chars: int) -> str:
    if max_chars < 0 or len(value) <= max_chars:
        return value
    return value[:max_chars] + "...[truncated]"


def _truncate_json(value: Any, max_chars: int) -> Any:
    rendered = json.dumps(value, ensure_ascii=False, default=str)
    if len(rendered) <= max_chars:
        return value
    return rendered[:max_chars] + "...[truncated]"


def _card(title: str, value: object) -> str:
    return f"<article class='card'><p>{escape(title)}</p><h2>{escape(str(value))}</h2></article>"
