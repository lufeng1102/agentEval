from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from evolution.regressions import append_regression_dataset, write_regression_dataset
from schemas import AgentTrace
from traces.normalize import agent_trace_to_case, read_agent_traces


def trace_failures_to_regressions(traces_path: str | Path, *, source: str = "auto", only_errors: bool = True, include_negative_outcomes: bool = False, limit: int | None = None) -> dict[str, Any]:
    traces = read_agent_traces(traces_path, source=source)
    cases = []
    for trace in traces:
        if only_errors and not _trace_failed(trace, include_negative_outcomes=include_negative_outcomes):
            continue
        case = agent_trace_to_case(trace, id_prefix="trace").model_dump(mode="json")
        case["id"] = f"trace_{_safe_id(trace.trace_id)}"
        tags = list(dict.fromkeys([*(case.get("tags") or []), "regression"]))
        if _trace_failed(trace, include_negative_outcomes=True) and "failure" not in tags:
            tags.append("failure")
        case["tags"] = tags
        metadata = dict(case.get("metadata") or {})
        trace_metadata = dict(metadata.get("trace") or {})
        trace_metadata.update(
            {
                "fingerprint": _fingerprint(trace),
                "review_status": "needs_review",
                "source_trace_id": trace.trace_id,
                "error_count": len(trace.errors),
                "error_span_count": sum(1 for span in trace.spans if span.error or span.status == "error"),
            }
        )
        metadata["trace"] = trace_metadata
        metadata["regression"] = {
            "source": "trace",
            "source_trace_id": trace.trace_id,
            "fingerprint": trace_metadata["fingerprint"],
            "status": "active",
            "severity": _severity(trace),
            "review_status": "needs_review",
            "seen_count": 1,
        }
        case["metadata"] = metadata
        case["expected"] = _expected(trace)
        case["rubric"] = _rubric(trace)
        cases.append(case)
        if limit is not None and len(cases) >= limit:
            break
    return {"metadata": {"generated_from_traces": True, "source": str(traces_path)}, "cases": cases}


def write_trace_regressions(path: str | Path, dataset: dict[str, Any]) -> None:
    write_regression_dataset(path, dataset)


def append_trace_regressions(path: str | Path, dataset: dict[str, Any], dedupe: bool = True) -> dict[str, Any]:
    return append_regression_dataset(path, dataset, dedupe=dedupe)


def _trace_failed(trace: AgentTrace, *, include_negative_outcomes: bool) -> bool:
    if trace.errors:
        return True
    if any(span.error or span.status == "error" for span in trace.spans):
        return True
    production = trace.metadata.get("production") if isinstance(trace.metadata.get("production"), dict) else {}
    if production.get("task_success") is False:
        return True
    if include_negative_outcomes:
        outcome = production.get("outcome") or trace.metadata.get("outcome") or {}
        user_outcome = production.get("user_outcome") or trace.metadata.get("user_outcome")
        if str(user_outcome).lower() in {"negative", "failed", "failure", "bad"}:
            return True
        if isinstance(outcome, dict) and outcome.get("success") is False:
            return True
    return False


def _expected(trace: AgentTrace) -> dict[str, Any]:
    return {
        "production_trace": {
            "trace_id": trace.trace_id,
            "source": trace.source,
            "errors": trace.errors,
            "error_spans": [span.name for span in trace.spans if span.error or span.status == "error"],
        },
        "spans": {"max_error_spans": 0},
    }


def _rubric(trace: AgentTrace) -> str:
    errors = "; ".join(trace.errors) or "; ".join(span.error or span.name for span in trace.spans if span.error or span.status == "error") or "observed production failure"
    return f"This regression was generated from production trace {trace.trace_id}. A passing response should address the original user need while avoiding the observed failure: {errors}"


def _severity(trace: AgentTrace) -> str:
    if trace.metadata.get("risk_level") in {"critical", "high"}:
        return "high"
    if any(span.kind == "tool" and (span.error or span.status == "error") for span in trace.spans):
        return "high"
    return "medium"


def _fingerprint(trace: AgentTrace) -> str:
    payload = {
        "input": trace.input,
        "errors": trace.errors,
        "error_spans": [(span.name, span.error, span.status) for span in trace.spans if span.error or span.status == "error"],
        "source": trace.source,
    }
    return hashlib.sha256(json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str).encode("utf-8")).hexdigest()


def _safe_id(value: str) -> str:
    return "".join(char if char.isalnum() or char in {"-", "_"} else "_" for char in value)[:96] or "item"
