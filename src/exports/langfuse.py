from __future__ import annotations

from typing import Any, Iterable

from exports.base import ExportBundle, build_trace_records

KIND_TO_TYPE = {"llm": "GENERATION", "tool": "TOOL", "retrieval": "RETRIEVER"}


def export_records(bundle: ExportBundle) -> Iterable[dict[str, Any]]:
    for record in build_trace_records(bundle):
        yield {
            "id": record.trace_id,
            "name": f"AgentEval case {record.case_id}",
            "input": record.input,
            "output": record.output,
            "metadata": {"agenteval_run_id": record.run_id, "case_id": record.case_id, "repeat_index": record.repeat_index, **record.metadata},
            "tags": record.metadata.get("tags", []),
            "observations": [_observation(span) for span in record.spans],
            "scores": [_score(result) for result in record.scores],
        }


def _observation(span) -> dict[str, Any]:
    return {
        "id": span.span_id,
        "parentObservationId": span.parent_span_id,
        "type": KIND_TO_TYPE.get(str(span.kind), "SPAN"),
        "name": span.name,
        "startTime": span.start_time,
        "endTime": span.end_time,
        "input": span.input,
        "output": span.output,
        "metadata": {"agenteval.kind": str(span.kind), "latency_ms": span.latency_ms, **(span.attributes or {})},
    }


def _score(result) -> dict[str, Any]:
    return {"name": result.evaluator, "value": result.score, "comment": result.failure_reason, "metadata": {"passed": result.passed, "failure_type": result.failure_type, "metrics": result.metrics}}
