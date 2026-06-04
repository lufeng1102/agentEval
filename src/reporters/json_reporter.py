from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path

from schemas import AgentRun, EvalCase, EvalResult


def summarize(cases: list[EvalCase], runs: list[AgentRun], results: list[EvalResult]) -> dict:
    pass_rate = sum(result.passed for result in results) / len(results) if results else 0
    avg_score = sum(result.score for result in results) / len(results) if results else 0
    latencies = sorted(run.latency_ms for run in runs)
    case_tags = {case.id: case.tags for case in cases}

    by_tag: dict[str, list[EvalResult]] = defaultdict(list)
    by_evaluator: dict[str, list[EvalResult]] = defaultdict(list)
    by_failure_type: dict[str, list[EvalResult]] = defaultdict(list)
    for result in results:
        by_evaluator[result.evaluator].append(result)
        if result.failure_type:
            by_failure_type[result.failure_type].append(result)
        for tag in case_tags.get(result.case_id, []):
            by_tag[tag].append(result)

    input_tokens = sum(run.usage.input_tokens for run in runs)
    output_tokens = sum(run.usage.output_tokens for run in runs)
    cache_creation = sum(run.usage.cache_creation_input_tokens for run in runs)
    cache_read = sum(run.usage.cache_read_input_tokens for run in runs)
    total_input = input_tokens + cache_creation + cache_read
    tool_calls = [call for run in runs for call in run.tool_calls]
    failed_tool_calls = [call for call in tool_calls if call.error]
    errors_by_case = {run.case_id: run.errors for run in runs if run.errors}

    return {
        "cases": len(cases),
        "runs": len(runs),
        "results": len(results),
        "failures": sum(not result.passed for result in results),
        "pass_rate": pass_rate,
        "avg_score": avg_score,
        "latency_ms": {
            "p50": _percentile(latencies, 50),
            "p95": _percentile(latencies, 95),
        },
        "usage": {
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "cache_creation_input_tokens": cache_creation,
            "cache_read_input_tokens": cache_read,
            "total_input_tokens": total_input,
            "cache_hit_rate": cache_read / total_input if total_input else 0,
        },
        "tool_calls": {
            "total": len(tool_calls),
            "failed": len(failed_tool_calls),
        },
        "errors": {
            "total": sum(len(run.errors) for run in runs),
            "by_case": errors_by_case,
        },
        "by_tag": _summarize_groups(by_tag),
        "by_evaluator": _summarize_groups(by_evaluator),
        "by_failure_type": _summarize_groups(by_failure_type),
        "stability": _stability(results),
    }


def write_json_report(path: str | Path, cases: list[EvalCase], runs: list[AgentRun], results: list[EvalResult]) -> None:
    payload = {
        "summary": summarize(cases, runs, results),
        "cases": [case.model_dump(mode="json") for case in cases],
        "runs": [run.model_dump(mode="json") for run in runs],
        "results": [result.model_dump(mode="json") for result in results],
    }
    Path(path).write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _summarize_groups(groups: dict[str, list[EvalResult]]) -> dict[str, dict[str, float | int]]:
    return {
        key: {
            "results": len(group_results),
            "pass_rate": sum(item.passed for item in group_results) / len(group_results),
            "avg_score": sum(item.score for item in group_results) / len(group_results),
        }
        for key, group_results in groups.items()
    }


def _stability(results: list[EvalResult]) -> dict:
    by_case: dict[str, list[EvalResult]] = defaultdict(list)
    for result in results:
        by_case[result.case_id].append(result)
    case_stats = {}
    flaky_cases = []
    case_pass_at_1 = []
    case_pass_any = []
    case_pass_all = []
    for case_id, case_results in by_case.items():
        repeat_indexes = {result.repeat_index for result in case_results}
        repeats = len(repeat_indexes)
        pass_rate = sum(result.passed for result in case_results) / len(case_results) if case_results else 0
        scores = [result.score for result in case_results]
        mean = sum(scores) / len(scores) if scores else 0
        variance = sum((score - mean) ** 2 for score in scores) / len(scores) if scores else 0
        passed_by_repeat = []
        for repeat_index in sorted(repeat_indexes):
            repeated = [result for result in case_results if result.repeat_index == repeat_index]
            passed_by_repeat.append(all(result.passed for result in repeated))
        flaky = len(set(passed_by_repeat)) > 1
        pass_at_1 = passed_by_repeat[0] if passed_by_repeat else False
        pass_at_k = any(passed_by_repeat)
        pass_all = all(passed_by_repeat) if passed_by_repeat else False
        case_pass_at_1.append(pass_at_1)
        case_pass_any.append(pass_at_k)
        case_pass_all.append(pass_all)
        if flaky:
            flaky_cases.append(case_id)
        case_stats[case_id] = {
            "repeats": repeats,
            "pass_rate": pass_rate,
            "score_mean": mean,
            "score_stddev": variance ** 0.5,
            "pass_at_1": pass_at_1,
            "pass_at_k": pass_at_k,
            "pass_all": pass_all,
            "flaky": flaky,
        }
    total_cases = len(case_stats)
    return {
        "cases": case_stats,
        "flaky_cases": flaky_cases,
        "pass_at_1": sum(case_pass_at_1) / total_cases if total_cases else 0,
        "pass_at_k": sum(case_pass_any) / total_cases if total_cases else 0,
        "pass_all": sum(case_pass_all) / total_cases if total_cases else 0,
    }


def _percentile(values: list[float], percentile: int) -> float:
    if not values:
        return 0.0
    index = min(len(values) - 1, round((percentile / 100) * (len(values) - 1)))
    return values[index]
