from __future__ import annotations

from typing import Any, Iterable

from exports.base import ExportBundle, build_trace_records


def export_records(bundle: ExportBundle) -> Iterable[dict[str, Any]]:
    for record in build_trace_records(bundle):
        yield {
            "id": f"{record.case_id}:{record.repeat_index}",
            "experiment_id": f"agenteval:{record.run_id}",
            "input": record.input,
            "expected": record.expected,
            "output": record.output,
            "scores": {result.evaluator: result.score for result in record.scores},
            "metadata": {"case_id": record.case_id, "repeat_index": record.repeat_index, "latency_ms": record.metadata.get("latency_ms"), "usage": record.metadata.get("usage", {}), "errors": record.metadata.get("errors", []), "manifest": record.metadata.get("manifest", {})},
            "span_attributes": [_span_attributes(span) for span in record.spans],
        }


def _span_attributes(span) -> dict[str, Any]:
    return {"span_id": span.span_id, "parent_span_id": span.parent_span_id, "name": span.name, "kind": str(span.kind), "latency_ms": span.latency_ms, "status": span.status}
