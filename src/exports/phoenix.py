from __future__ import annotations

from typing import Any, Iterable

from exports.base import ExportBundle, build_trace_records

KIND_TO_OPENINFERENCE = {"llm": "LLM", "tool": "TOOL", "retrieval": "RETRIEVER", "embedding": "EMBEDDING", "chain": "CHAIN", "agent": "AGENT", "api": "TOOL", "custom": "CHAIN"}


def export_records(bundle: ExportBundle) -> Iterable[dict[str, Any]]:
    for record in build_trace_records(bundle):
        if not record.spans:
            yield _root_span(record)
        for span in record.spans:
            yield {
                "context": {"trace_id": record.trace_id, "span_id": span.span_id},
                "parent_id": span.parent_span_id,
                "name": span.name,
                "start_time": span.start_time,
                "end_time": span.end_time,
                "status_code": "ERROR" if span.error or span.status == "error" else "OK",
                "attributes": {
                    "openinference.span.kind": KIND_TO_OPENINFERENCE.get(str(span.kind), "CHAIN"),
                    "input.value": span.input,
                    "output.value": span.output,
                    "agenteval.case_id": record.case_id,
                    "agenteval.repeat_index": record.repeat_index,
                    "agenteval.run_id": record.run_id,
                    "agenteval.latency_ms": span.latency_ms,
                    **(span.attributes or {}),
                },
                "events": span.events,
            }


def _root_span(record) -> dict[str, Any]:
    return {
        "context": {"trace_id": record.trace_id, "span_id": f"root_{record.case_id}_{record.repeat_index}"},
        "parent_id": None,
        "name": f"AgentEval case {record.case_id}",
        "start_time": None,
        "end_time": None,
        "status_code": "ERROR" if record.metadata.get("errors") else "OK",
        "attributes": {"openinference.span.kind": "AGENT", "input.value": record.input, "output.value": record.output, "agenteval.case_id": record.case_id, "agenteval.repeat_index": record.repeat_index, "agenteval.run_id": record.run_id},
        "events": [],
    }
