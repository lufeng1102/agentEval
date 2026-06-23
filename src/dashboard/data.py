from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Protocol

from pydantic import BaseModel, Field

from compare import compare_runs
from runners.trace import read_jsonl
from schemas import AgentRun, EvalResult, TraceSpan


class Page(BaseModel):
    items: list[Any]
    total: int
    page: int = 1
    page_size: int = 100


class CaseFilters(BaseModel):
    status: str | None = None
    evaluator: str | None = None
    tag: str | None = None
    risk_level: str | None = None
    capability: str | None = None
    min_latency_ms: float | None = None
    max_latency_ms: float | None = None


class RunSummary(BaseModel):
    run_id: str
    run_dir: str
    summary: dict[str, Any] = Field(default_factory=dict)
    case_count: int = 0
    result_count: int = 0
    pass_rate: float = 0
    avg_score: float = 0
    error_count: int = 0
    failed_case_count: int = 0
    total_tool_calls: int = 0
    total_input_tokens: int = 0
    total_output_tokens: int = 0


class CaseRow(BaseModel):
    case_id: str
    repeat_index: int = 0
    name: str | None = None
    tags: list[str] = Field(default_factory=list)
    status: str = "unknown"
    score: float | None = None
    failed_evaluators: list[str] = Field(default_factory=list)
    latency_ms: float | None = None
    errors: list[str] = Field(default_factory=list)
    risk_level: str | None = None
    capability: str | None = None


class SpanRow(BaseModel):
    span_id: str
    parent_span_id: str | None = None
    depth: int = 0
    name: str
    kind: str
    latency_ms: float | None = None
    status: str = "unset"
    has_error: bool = False


class TraceView(BaseModel):
    trace_id: str
    root_span_id: str | None = None
    flat_spans: list[SpanRow] = Field(default_factory=list)
    span_count: int = 0
    tool_call_count: int = 0


class CaseDetail(BaseModel):
    case: dict[str, Any] = Field(default_factory=dict)
    run: AgentRun | None = None
    results: list[EvalResult] = Field(default_factory=list)
    trace: TraceView | None = None


class DashboardDataSource(Protocol):
    def get_run_summary(self, run_id: str = "latest") -> RunSummary: ...
    def list_cases(self, run_id: str = "latest", filters: CaseFilters | None = None, *, page: int = 1, page_size: int = 100) -> Page: ...
    def get_case_detail(self, run_id: str, case_id: str, repeat_index: int = 0) -> CaseDetail: ...
    def get_trace(self, run_id: str, case_id: str, repeat_index: int = 0) -> TraceView: ...
    def get_results(self, run_id: str, case_id: str | None = None) -> list[EvalResult]: ...


class LocalRunDataSource:
    def __init__(self, run_dir: str | Path):
        self.run_dir = Path(run_dir)
        self.report = _read_json(self.run_dir / "report.json") if (self.run_dir / "report.json").exists() else {}
        self.manifest = _read_json(self.run_dir / "manifest.json") if (self.run_dir / "manifest.json").exists() else {}
        self.runs = [AgentRun.model_validate(item) for item in read_jsonl(self.run_dir / "traces.jsonl")]
        result_items = read_jsonl(self.run_dir / "results.jsonl") or self.report.get("results", []) or []
        self.results = [EvalResult.model_validate(item) for item in result_items]
        self.cases = [case for case in self.report.get("cases", []) or [] if isinstance(case, dict)]
        self._cases_by_id = {str(case.get("id")): case for case in self.cases}
        self._runs_by_key = {(run.case_id, run.repeat_index): run for run in self.runs}

    def get_run_summary(self, run_id: str = "latest") -> RunSummary:
        summary = self.report.get("summary", {}) or {}
        failed_cases = {result.case_id for result in self.results if not result.passed}
        return RunSummary(
            run_id=str(self.manifest.get("run_id") or self.manifest.get("id") or self.run_dir.name if run_id == "latest" else run_id),
            run_dir=str(self.run_dir),
            summary=summary,
            case_count=len(self.cases) or len({run.case_id for run in self.runs}),
            result_count=len(self.results),
            pass_rate=float(summary.get("pass_rate", 0) or 0),
            avg_score=float(summary.get("avg_score", 0) or 0),
            error_count=sum(len(run.errors) for run in self.runs),
            failed_case_count=len(failed_cases),
            total_tool_calls=sum(len(run.tool_calls) for run in self.runs),
            total_input_tokens=sum(run.usage.total_input_tokens for run in self.runs),
            total_output_tokens=sum(run.usage.output_tokens for run in self.runs),
        )

    def list_cases(self, run_id: str = "latest", filters: CaseFilters | None = None, *, page: int = 1, page_size: int = 100) -> Page:
        filters = filters or CaseFilters()
        rows = [_case_row(case_id, repeat_index, self._cases_by_id.get(case_id, {}), run, self._results_for(case_id, repeat_index)) for case_id, repeat_index, run in self._case_keys()]
        rows = [row for row in rows if _matches_filters(row, filters)]
        start = max(page - 1, 0) * page_size
        return Page(items=rows[start : start + page_size], total=len(rows), page=page, page_size=page_size)

    def get_case_detail(self, run_id: str, case_id: str, repeat_index: int = 0) -> CaseDetail:
        run = self._runs_by_key.get((case_id, repeat_index))
        return CaseDetail(case=self._cases_by_id.get(case_id, {}), run=run, results=self._results_for(case_id, repeat_index), trace=self.get_trace(run_id, case_id, repeat_index) if run else None)

    def get_trace(self, run_id: str, case_id: str, repeat_index: int = 0) -> TraceView:
        run = self._runs_by_key.get((case_id, repeat_index))
        if run is None:
            return TraceView(trace_id=f"{case_id}:{repeat_index}")
        trace_id = str((run.raw_response or {}).get("trace_id") or f"{case_id}:{repeat_index}")
        span_rows = _span_rows(run.spans)
        root = next((span.span_id for span in run.spans if not span.parent_span_id), None)
        return TraceView(trace_id=trace_id, root_span_id=root, flat_spans=span_rows, span_count=len(run.spans), tool_call_count=len(run.tool_calls))

    def get_results(self, run_id: str, case_id: str | None = None) -> list[EvalResult]:
        if case_id is None:
            return list(self.results)
        return [result for result in self.results if result.case_id == case_id]

    def compare_to(self, baseline_run_dir: str | Path) -> dict[str, Any]:
        return compare_runs(baseline_run_dir, self.run_dir)

    def _results_for(self, case_id: str, repeat_index: int) -> list[EvalResult]:
        return [result for result in self.results if result.case_id == case_id and result.repeat_index == repeat_index]

    def _case_keys(self) -> list[tuple[str, int, AgentRun | None]]:
        keys = sorted(set(self._runs_by_key) | {(str(case.get("id")), 0) for case in self.cases})
        return [(case_id, repeat_index, self._runs_by_key.get((case_id, repeat_index))) for case_id, repeat_index in keys]


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _case_row(case_id: str, repeat_index: int, case: dict[str, Any], run: AgentRun | None, results: list[EvalResult]) -> CaseRow:
    failed = [result.evaluator for result in results if not result.passed]
    score = sum(result.score for result in results) / len(results) if results else None
    metadata = case.get("metadata", {}) or {}
    errors = run.errors if run else []
    return CaseRow(
        case_id=case_id,
        repeat_index=repeat_index,
        name=case.get("name"),
        tags=list(case.get("tags", []) or []),
        status="error" if errors else "failed" if failed else "passed" if results else "unknown",
        score=score,
        failed_evaluators=failed,
        latency_ms=run.latency_ms if run else None,
        errors=errors,
        risk_level=metadata.get("risk_level"),
        capability=metadata.get("capability"),
    )


def _matches_filters(row: CaseRow, filters: CaseFilters) -> bool:
    if filters.status and row.status != filters.status:
        if not (filters.status == "failed" and row.failed_evaluators):
            return False
    if filters.evaluator and filters.evaluator not in row.failed_evaluators:
        return False
    if filters.tag and filters.tag not in row.tags:
        return False
    if filters.risk_level and row.risk_level != filters.risk_level:
        return False
    if filters.capability and row.capability != filters.capability:
        return False
    if filters.min_latency_ms is not None and (row.latency_ms is None or row.latency_ms < filters.min_latency_ms):
        return False
    if filters.max_latency_ms is not None and (row.latency_ms is None or row.latency_ms > filters.max_latency_ms):
        return False
    return True


def _span_rows(spans: list[TraceSpan]) -> list[SpanRow]:
    children: dict[str | None, list[TraceSpan]] = {}
    for span in spans:
        children.setdefault(span.parent_span_id, []).append(span)
    rows: list[SpanRow] = []

    def visit(span: TraceSpan, depth: int) -> None:
        rows.append(SpanRow(span_id=span.span_id, parent_span_id=span.parent_span_id, depth=depth, name=span.name, kind=str(span.kind), latency_ms=span.latency_ms, status=str(span.status), has_error=bool(span.error)))
        for child in children.get(span.span_id, []):
            visit(child, depth + 1)

    roots = children.get(None, []) or spans
    seen = set()
    for root in roots:
        if root.span_id in seen:
            continue
        before = len(rows)
        visit(root, 0)
        seen.update(row.span_id for row in rows[before:])
    return rows
