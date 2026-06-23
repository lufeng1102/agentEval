from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Iterable, Literal

from pydantic import BaseModel, Field

from runners.trace import read_jsonl
from schemas import AgentRun, EvalResult, TraceSpan, ToolCall


class ValidationIssue(BaseModel):
    severity: Literal["error", "warning"]
    path: str
    message: str


class ExportBundle(BaseModel):
    run_id: str
    manifest: dict[str, Any] = Field(default_factory=dict)
    summary: dict[str, Any] = Field(default_factory=dict)
    runs: list[AgentRun] = Field(default_factory=list)
    results: list[EvalResult] = Field(default_factory=list)
    cases: list[dict[str, Any]] = Field(default_factory=list)


class ExportTraceRecord(BaseModel):
    trace_id: str
    run_id: str
    case_id: str
    repeat_index: int
    input: Any = None
    expected: Any = None
    output: str = ""
    spans: list[TraceSpan] = Field(default_factory=list)
    tool_calls: list[ToolCall] = Field(default_factory=list)
    scores: list[EvalResult] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


def load_export_bundle(run_dir: str | Path) -> ExportBundle:
    path = Path(run_dir)
    report = _read_json(path / "report.json") if (path / "report.json").exists() else {}
    manifest = _read_json(path / "manifest.json") if (path / "manifest.json").exists() else {}
    runs = [AgentRun.model_validate(item) for item in read_jsonl(path / "traces.jsonl")]
    results_path = path / "results.jsonl"
    result_items = read_jsonl(results_path) if results_path.exists() else report.get("results", []) or []
    results = [EvalResult.model_validate(item) for item in result_items]
    run_id = str(manifest.get("run_id") or manifest.get("id") or path.name)
    return ExportBundle(run_id=run_id, manifest=manifest, summary=report.get("summary", {}) or {}, runs=runs, results=results, cases=report.get("cases", []) or [])


def build_trace_records(bundle: ExportBundle) -> list[ExportTraceRecord]:
    cases = {str(case.get("id")): case for case in bundle.cases if isinstance(case, dict)}
    results_by_key: dict[tuple[str, int], list[EvalResult]] = {}
    for result in bundle.results:
        results_by_key.setdefault((result.case_id, result.repeat_index), []).append(result)
    records = []
    for run in bundle.runs:
        case = cases.get(run.case_id, {})
        trace_id = str((run.raw_response or {}).get("trace_id") or f"{run.case_id}:{run.repeat_index}")
        spans = list(run.spans)
        if run.tool_calls and not any(str(span.kind) == "tool" for span in spans):
            spans.extend(_synthetic_tool_spans(trace_id, run.case_id, run.repeat_index, run.tool_calls))
        records.append(
            ExportTraceRecord(
                trace_id=trace_id,
                run_id=bundle.run_id,
                case_id=run.case_id,
                repeat_index=run.repeat_index,
                input=case.get("input") if case else _message_input(run),
                expected=case.get("expected") if case else None,
                output=run.final_output,
                spans=spans,
                tool_calls=run.tool_calls,
                scores=results_by_key.get((run.case_id, run.repeat_index), []),
                metadata={"manifest": bundle.manifest, "summary": bundle.summary, "artifacts": run.artifacts, "usage": run.usage.model_dump(mode="json"), "latency_ms": run.latency_ms, "errors": run.errors, "tags": case.get("tags", []) if case else []},
            )
        )
    return records


def export_run(target: str, run_dir: str | Path, out: str | Path, *, validate: bool = False) -> list[ValidationIssue]:
    bundle = load_export_bundle(run_dir)
    if target == "langfuse":
        from exports.langfuse import export_records
    elif target == "phoenix":
        from exports.phoenix import export_records
    elif target == "braintrust":
        from exports.braintrust import export_records
    else:
        raise ValueError(f"unsupported export target: {target}")
    records = list(export_records(bundle))
    issues = validate_records(target, records) if validate else []
    write_jsonl(out, records)
    return issues


def validate_records(target: str, records: Iterable[dict[str, Any]]) -> list[ValidationIssue]:
    issues = []
    for index, record in enumerate(records):
        try:
            json.dumps(record)
        except (TypeError, ValueError) as exc:
            issues.append(ValidationIssue(severity="error", path=f"records[{index}]", message=f"record is not JSON serializable: {exc}"))
        if target == "langfuse":
            _validate_langfuse(record, index, issues)
        elif target == "phoenix":
            _validate_phoenix(record, index, issues)
        elif target == "braintrust":
            _validate_braintrust(record, index, issues)
    return issues


def write_jsonl(path: str | Path, records: Iterable[dict[str, Any]]) -> None:
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", encoding="utf-8") as handle:
        for record in records:
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _message_input(run: AgentRun) -> Any:
    if not run.messages:
        return None
    if len(run.messages) == 1:
        return run.messages[0].content
    return [message.model_dump(mode="json") for message in run.messages]


def _synthetic_tool_spans(trace_id: str, case_id: str, repeat_index: int, tool_calls: list[ToolCall]) -> list[TraceSpan]:
    spans = []
    for index, call in enumerate(tool_calls):
        spans.append(TraceSpan(span_id=f"synthetic_tool_{case_id}_{repeat_index}_{index}", trace_id=trace_id, name=call.name, kind="tool", status="error" if call.error else "ok", input=call.input, output=call.output, error=call.error, attributes={"synthetic": True}))
    return spans


def _validate_langfuse(record: dict[str, Any], index: int, issues: list[ValidationIssue]) -> None:
    for key in ["id", "name", "observations", "scores"]:
        if key not in record:
            issues.append(ValidationIssue(severity="error", path=f"records[{index}].{key}", message="required field missing"))
    for obs_index, observation in enumerate(record.get("observations", []) or []):
        if not observation.get("id"):
            issues.append(ValidationIssue(severity="error", path=f"records[{index}].observations[{obs_index}].id", message="observation id is required"))


def _validate_phoenix(record: dict[str, Any], index: int, issues: list[ValidationIssue]) -> None:
    context = record.get("context") or {}
    if not context.get("trace_id"):
        issues.append(ValidationIssue(severity="error", path=f"records[{index}].context.trace_id", message="trace_id is required"))
    if not context.get("span_id"):
        issues.append(ValidationIssue(severity="error", path=f"records[{index}].context.span_id", message="span_id is required"))
    if not record.get("name"):
        issues.append(ValidationIssue(severity="error", path=f"records[{index}].name", message="name is required"))


def _validate_braintrust(record: dict[str, Any], index: int, issues: list[ValidationIssue]) -> None:
    for key in ["id", "experiment_id", "input", "output", "scores"]:
        if key not in record:
            issues.append(ValidationIssue(severity="error", path=f"records[{index}].{key}", message="required field missing"))
    for name, value in (record.get("scores") or {}).items():
        if not isinstance(value, (int, float)):
            issues.append(ValidationIssue(severity="error", path=f"records[{index}].scores.{name}", message="score must be numeric"))
