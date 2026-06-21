from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from production.ingest import load_production_events
from production.models import ProductionEvent
from runners.trace import read_jsonl
from schemas import AgentRun, AgentTrace, ChatMessage, EvalCase, ToolCall, TraceSpan, Usage

_TRACE_KEYS = ("traces", "spans", "events", "records", "runs")


def load_trace_payloads(path: str | Path) -> list[dict[str, Any]]:
    file_path = Path(path)
    if file_path.suffix == ".jsonl":
        return read_jsonl(file_path)
    data = json.loads(file_path.read_text(encoding="utf-8"))
    if isinstance(data, list):
        return [item for item in data if isinstance(item, dict)]
    if isinstance(data, dict):
        for key in _TRACE_KEYS:
            values = data.get(key)
            if isinstance(values, list):
                return [item for item in values if isinstance(item, dict)]
        if data.get("trace_id") or data.get("case_id") or data.get("event_id"):
            return [data]
    raise ValueError(f"unsupported trace input format: {path}")


def read_agent_traces(path: str | Path, source: str = "auto") -> list[AgentTrace]:
    return normalize_trace_payloads(path, source=source)


def normalize_trace_payloads(path: str | Path, source: str = "auto") -> list[AgentTrace]:
    normalized_source = source.lower()
    if normalized_source == "production":
        return production_events_to_traces(load_production_events(path))
    payloads = load_trace_payloads(path)
    if normalized_source == "auto":
        normalized_source = _detect_source(payloads)
    if normalized_source in {"otel", "openinference", "phoenix"}:
        return _otel_payloads_to_traces(payloads, normalized_source)
    if normalized_source == "langfuse":
        return _langfuse_payloads_to_traces(payloads)
    if normalized_source == "agenteval":
        return [_agent_eval_payload_to_trace(item) for item in payloads]
    return [_generic_payload_to_trace(item, normalized_source) for item in payloads]


def production_events_to_traces(events: list[ProductionEvent]) -> list[AgentTrace]:
    traces: list[AgentTrace] = []
    for event in events:
        trace_id = event.trace_id or event.event_id
        tool_calls = [_tool_call(call) for call in event.tool_calls]
        spans = [_span_from_tool_call(call, trace_id, index) for index, call in enumerate(event.tool_calls)]
        metadata = dict(event.metadata or {})
        metadata["production"] = {
            "event_id": event.event_id,
            "variant": event.variant,
            "experiment_id": event.experiment_id,
            "task_success": event.task_success,
            "user_outcome": event.user_outcome,
            "outcome": event.outcome,
        }
        traces.append(
            AgentTrace(
                trace_id=trace_id,
                case_id=str(metadata.get("case_id")) if metadata.get("case_id") else None,
                session_id=event.session_id,
                user_id_hash=event.user_id_hash,
                agent_id=event.agent_id,
                agent_version=event.agent_version,
                source="production",
                input=_message_input(event.input),
                final_output=event.final_output,
                messages=_chat_messages(event.messages),
                spans=spans,
                tool_calls=tool_calls,
                usage=_usage(event.usage),
                latency_ms=float(event.latency_ms or 0),
                errors=list(event.errors),
                tags=list(event.tags),
                metadata=metadata,
            )
        )
    return traces


def agent_trace_to_run(trace: AgentTrace, repeat_index: int = 0) -> AgentRun:
    case_id = _case_id_for_trace(trace)
    artifacts = {
        "trace": {
            "trace_id": trace.trace_id,
            "source": trace.source,
            "session_id": trace.session_id,
            "agent_id": trace.agent_id,
            "agent_version": trace.agent_version,
        }
    }
    return AgentRun(
        case_id=case_id,
        repeat_index=repeat_index,
        messages=trace.messages,
        final_output=trace.final_output,
        tool_calls=trace.tool_calls,
        spans=trace.spans,
        latency_ms=trace.latency_ms,
        usage=trace.usage,
        errors=trace.errors,
        raw_response={"trace": trace.model_dump(mode="json")},
        artifacts=artifacts,
    )


def agent_trace_to_case(trace: AgentTrace, *, id_prefix: str = "trace") -> EvalCase:
    case_id = _case_id_for_trace(trace, id_prefix=id_prefix)
    tags = list(dict.fromkeys(["trace", *( [trace.source] if trace.source else []), *trace.tags]))
    if trace.source == "production" and "production" not in tags:
        tags.insert(0, "production")
    metadata = dict(trace.metadata or {})
    metadata["trace"] = {
        "trace_id": trace.trace_id,
        "source": trace.source,
        "session_id": trace.session_id,
        "agent_id": trace.agent_id,
        "agent_version": trace.agent_version,
    }
    return EvalCase(
        id=case_id,
        input=trace.input or _input_from_messages(trace.messages) or "production trace",
        expected=_expected_from_trace(trace),
        tags=tags,
        metadata=metadata,
    )


def _detect_source(payloads: list[dict[str, Any]]) -> str:
    sample = payloads[0] if payloads else {}
    if sample.get("observations") or sample.get("input") is not None and sample.get("output") is not None and sample.get("id") and not sample.get("span_id"):
        return "langfuse"
    attributes = sample.get("attributes") or sample.get("resource", {}).get("attributes") or {}
    if any(str(key).startswith("openinference") for key in attributes):
        return "openinference"
    if sample.get("trace_id") and isinstance(sample.get("spans"), list):
        return "agenteval"
    if sample.get("span_id") or sample.get("context", {}).get("span_id") or sample.get("trace_id"):
        return "otel"
    if sample.get("event_id"):
        return "production"
    return "agenteval"


def _agent_eval_payload_to_trace(item: dict[str, Any]) -> AgentTrace:
    if item.get("trace_id") and (item.get("spans") is not None or item.get("source")):
        return AgentTrace.model_validate(item)
    run = AgentRun.model_validate(item)
    trace_id = str(run.artifacts.get("trace", {}).get("trace_id") or run.case_id)
    source = str(run.artifacts.get("trace", {}).get("source") or "agenteval")
    return AgentTrace(
        trace_id=trace_id,
        case_id=run.case_id,
        source=source,
        final_output=run.final_output,
        messages=run.messages,
        spans=run.spans,
        tool_calls=run.tool_calls,
        usage=run.usage,
        latency_ms=run.latency_ms,
        errors=run.errors,
        metadata={"artifacts": run.artifacts},
    )


def _generic_payload_to_trace(item: dict[str, Any], source: str) -> AgentTrace:
    trace_id = str(item.get("trace_id") or item.get("id") or item.get("event_id") or _stable_id(item))
    spans = [_span(span, trace_id, index) for index, span in enumerate(item.get("spans") or item.get("observations") or []) if isinstance(span, dict)]
    return AgentTrace(
        trace_id=trace_id,
        case_id=str(item.get("case_id")) if item.get("case_id") else None,
        session_id=item.get("session_id"),
        user_id_hash=item.get("user_id_hash"),
        agent_id=item.get("agent_id"),
        agent_version=item.get("agent_version"),
        source=source,
        input=_message_input(item.get("input")),
        final_output=str(item.get("final_output") or item.get("output") or ""),
        messages=_chat_messages(item.get("messages") or []),
        spans=spans,
        tool_calls=[_tool_call(call) for call in item.get("tool_calls") or [] if isinstance(call, dict)],
        usage=_usage(item.get("usage") or {}),
        latency_ms=float(item.get("latency_ms") or 0),
        errors=[str(error) for error in item.get("errors") or []],
        tags=[str(tag) for tag in item.get("tags") or []],
        metadata=dict(item.get("metadata") or {}),
    )


def _otel_payloads_to_traces(payloads: list[dict[str, Any]], source: str) -> list[AgentTrace]:
    grouped: dict[str, list[TraceSpan]] = {}
    first_payloads: dict[str, dict[str, Any]] = {}
    for index, item in enumerate(payloads):
        trace_id = str(item.get("trace_id") or item.get("context", {}).get("trace_id") or item.get("traceId") or _stable_id(item))
        grouped.setdefault(trace_id, []).append(_span(item, trace_id, index))
        first_payloads.setdefault(trace_id, item)
    traces = []
    for trace_id, spans in grouped.items():
        first = first_payloads[trace_id]
        traces.append(
            AgentTrace(
                trace_id=trace_id,
                source=source,
                input=_message_input(first.get("input") or _attribute(first, "input.value") or _attribute(first, "llm.input_messages")),
                final_output=str(first.get("final_output") or first.get("output") or _attribute(first, "output.value") or ""),
                spans=spans,
                tool_calls=[_tool_from_span(span) for span in spans if span.kind == "tool"],
                latency_ms=sum(span.latency_ms or 0 for span in spans),
                errors=[span.error for span in spans if span.error],
                tags=[source],
                metadata={"span_count": len(spans)},
            )
        )
    return traces


def _langfuse_payloads_to_traces(payloads: list[dict[str, Any]]) -> list[AgentTrace]:
    traces = []
    for item in payloads:
        trace_id = str(item.get("trace_id") or item.get("id") or _stable_id(item))
        observations = item.get("observations") or item.get("spans") or []
        spans = [_span(obs, trace_id, index) for index, obs in enumerate(observations) if isinstance(obs, dict)]
        traces.append(
            AgentTrace(
                trace_id=trace_id,
                case_id=str(item.get("case_id")) if item.get("case_id") else None,
                session_id=item.get("session_id") or item.get("sessionId"),
                user_id_hash=item.get("user_id") or item.get("userId"),
                source="langfuse",
                input=_message_input(item.get("input")),
                final_output=str(item.get("final_output") or item.get("output") or ""),
                messages=_chat_messages(item.get("messages") or []),
                spans=spans,
                tool_calls=[_tool_from_span(span) for span in spans if span.kind == "tool"],
                latency_ms=float(item.get("latency_ms") or item.get("latency") or 0),
                errors=[span.error for span in spans if span.error],
                tags=[str(tag) for tag in item.get("tags") or []],
                metadata={"langfuse": {key: value for key, value in item.items() if key not in {"observations", "spans"}}},
            )
        )
    return traces


def _span(item: dict[str, Any], trace_id: str, index: int) -> TraceSpan:
    attributes = dict(item.get("attributes") or item.get("metadata") or {})
    kind = _span_kind(item, attributes)
    error = item.get("error") or item.get("status", {}).get("message") if isinstance(item.get("status"), dict) else item.get("error")
    status = _span_status(item, error)
    return TraceSpan(
        span_id=str(item.get("span_id") or item.get("spanId") or item.get("id") or f"{trace_id}-{index}"),
        trace_id=trace_id,
        parent_span_id=item.get("parent_span_id") or item.get("parentSpanId") or item.get("parent_id"),
        name=str(item.get("name") or item.get("operation") or attributes.get("name") or kind),
        kind=kind,
        start_time=item.get("start_time") or item.get("startTime") or item.get("start_time_unix_nano"),
        end_time=item.get("end_time") or item.get("endTime") or item.get("end_time_unix_nano"),
        latency_ms=_latency_ms(item),
        status=status,
        input=item.get("input") or attributes.get("input.value"),
        output=item.get("output") or attributes.get("output.value"),
        error=str(error) if error else None,
        attributes=attributes,
        events=[event for event in item.get("events") or [] if isinstance(event, dict)],
    )


def _span_from_tool_call(call: dict[str, Any], trace_id: str, index: int) -> TraceSpan:
    return TraceSpan(
        span_id=str(call.get("id") or f"{trace_id}-tool-{index}"),
        trace_id=trace_id,
        name=str(call.get("name") or call.get("tool") or "tool"),
        kind="tool",
        status="error" if call.get("error") else "ok",
        input=call.get("input") or {},
        output=call.get("output"),
        error=str(call.get("error")) if call.get("error") else None,
        attributes={key: value for key, value in call.items() if key not in {"id", "name", "tool", "input", "output", "error"}},
    )


def _tool_call(call: dict[str, Any]) -> ToolCall:
    return ToolCall(name=str(call.get("name") or call.get("tool") or "tool"), input=dict(call.get("input") or call.get("arguments") or {}), output=call.get("output"), error=str(call.get("error")) if call.get("error") else None)


def _tool_from_span(span: TraceSpan) -> ToolCall:
    return ToolCall(name=span.name, input=span.input if isinstance(span.input, dict) else {}, output=span.output, error=span.error)


def _span_kind(item: dict[str, Any], attributes: dict[str, Any]) -> str:
    raw = item.get("kind") or item.get("type") or attributes.get("openinference.span.kind") or attributes.get("span.kind") or attributes.get("langfuse.observation.type") or "custom"
    value = str(raw).lower()
    mapping = {"tool": "tool", "llm": "llm", "chain": "chain", "retriever": "retrieval", "retrieval": "retrieval", "embedding": "embedding", "agent": "agent"}
    return mapping.get(value, value if value in {"api", "custom"} else "custom")


def _span_status(item: dict[str, Any], error: Any) -> str:
    if error:
        return "error"
    status = item.get("status")
    if isinstance(status, dict):
        status = status.get("code") or status.get("status_code")
    if status is None:
        return "unset"
    value = str(status).lower()
    if value in {"ok", "success", "status_code_ok", "1"}:
        return "ok"
    if value in {"error", "failed", "status_code_error", "2"}:
        return "error"
    return value


def _latency_ms(item: dict[str, Any]) -> float | None:
    if item.get("latency_ms") is not None:
        return float(item["latency_ms"])
    if item.get("duration_ms") is not None:
        return float(item["duration_ms"])
    return None


def _attribute(item: dict[str, Any], key: str) -> Any:
    return (item.get("attributes") or {}).get(key)


def _usage(data: dict[str, Any]) -> Usage:
    return Usage(
        input_tokens=int(data.get("input_tokens") or data.get("prompt_tokens") or 0),
        output_tokens=int(data.get("output_tokens") or data.get("completion_tokens") or 0),
        cache_creation_input_tokens=int(data.get("cache_creation_input_tokens") or 0),
        cache_read_input_tokens=int(data.get("cache_read_input_tokens") or 0),
    )


def _chat_messages(messages: list[dict[str, Any]]) -> list[ChatMessage]:
    parsed = []
    for message in messages:
        if isinstance(message, ChatMessage):
            parsed.append(message)
        elif isinstance(message, dict) and message.get("role") and "content" in message:
            parsed.append(ChatMessage.model_validate(message))
    return parsed


def _message_input(value: Any) -> str | list[ChatMessage] | None:
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        messages = _chat_messages(value)
        return messages or None
    return None


def _input_from_messages(messages: list[ChatMessage]) -> str | None:
    for message in messages:
        if message.role == "user" and message.content:
            return str(message.content)
    return None


def _expected_from_trace(trace: AgentTrace) -> dict[str, Any]:
    expected: dict[str, Any] = {"production_trace": {"trace_id": trace.trace_id, "source": trace.source}}
    if trace.tool_calls:
        expected["tool_calls"] = [{"name": call.name, "input": call.input} for call in trace.tool_calls]
    if trace.spans:
        expected["spans"] = {"max_error_spans": 0}
    return expected


def _case_id_for_trace(trace: AgentTrace, id_prefix: str = "trace") -> str:
    if trace.case_id:
        return trace.case_id
    return f"{id_prefix}_{_safe_id(trace.trace_id)}"


def _safe_id(value: str) -> str:
    return "".join(char if char.isalnum() or char in {"-", "_"} else "_" for char in value)[:96] or "item"


def _stable_id(item: dict[str, Any]) -> str:
    payload = json.dumps(item, ensure_ascii=False, sort_keys=True, default=str)
    return hashlib.sha1(payload.encode("utf-8")).hexdigest()[:16]
