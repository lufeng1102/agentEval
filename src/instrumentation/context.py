from __future__ import annotations

import contextvars
import functools
import hashlib
import inspect
import logging
import time
from collections.abc import Awaitable, Callable
from types import TracebackType
from typing import Any, ParamSpec, TypeVar

from schemas import AgentTrace, ChatMessage, ToolCall, TraceSpan, Usage
from instrumentation.redaction import redact_value
from instrumentation.schema import Redactor, TraceConfig
from instrumentation.writer import AppendJsonlTraceWriter

LOGGER = logging.getLogger(__name__)
P = ParamSpec("P")
T = TypeVar("T")

_CURRENT_TRACER: contextvars.ContextVar["AgentEvalTracer | None"] = contextvars.ContextVar("agenteval_current_tracer", default=None)


class AgentEvalTracer:
    def __init__(
        self,
        trace_path: str,
        *,
        source: str = "sdk",
        case_id: str | None = None,
        session_id: str | None = None,
        agent_id: str | None = None,
        agent_version: str | None = None,
        user_id_hash: str | None = None,
        tags: list[str] | None = None,
        metadata: dict[str, Any] | None = None,
        sample_rate: float = 1.0,
        fail_open: bool = True,
        redaction_enabled: bool = True,
        redactor: Redactor | None = None,
        writer: AppendJsonlTraceWriter | None = None,
    ):
        self.config = TraceConfig(
            trace_path=trace_path,
            source=source,
            case_id=case_id,
            session_id=session_id,
            agent_id=agent_id,
            agent_version=agent_version,
            user_id_hash=user_id_hash,
            tags=tags or [],
            metadata=metadata or {},
            sample_rate=sample_rate,
            fail_open=fail_open,
            redaction_enabled=redaction_enabled,
        )
        self.redactor = redactor
        self.writer = writer or AppendJsonlTraceWriter(self.config.trace_path)
        self.trace_id = str(self.config.metadata.get("trace_id") or _stable_id("trace", self.config.case_id or "sdk", time.perf_counter_ns()))
        self.messages: list[ChatMessage] = []
        self.spans: list[TraceSpan] = []
        self.tool_calls: list[ToolCall] = []
        self.usage = Usage()
        self.errors: list[str] = []
        self.input: Any = None
        self.final_output = ""
        self._started = 0.0
        self._span_stack: list[str] = []
        self._token: contextvars.Token[AgentEvalTracer | None] | None = None

    def __enter__(self) -> AgentEvalTracer:
        self._started = time.perf_counter()
        self._token = _CURRENT_TRACER.set(self)
        return self

    def __exit__(self, exc_type: type[BaseException] | None, exc: BaseException | None, traceback: TracebackType | None) -> bool:
        if exc is not None:
            self.record_error(exc)
        self.flush_safely()
        if self._token is not None:
            _CURRENT_TRACER.reset(self._token)
        return False

    async def __aenter__(self) -> AgentEvalTracer:
        return self.__enter__()

    async def __aexit__(self, exc_type: type[BaseException] | None, exc: BaseException | None, traceback: TracebackType | None) -> bool:
        return self.__exit__(exc_type, exc, traceback)

    def add_message(self, role: str, content: str | list[dict[str, Any]]) -> None:
        self.messages.append(ChatMessage(role=role, content=content))
        if role == "user" and self.input is None:
            self.input = content

    def set_final_output(self, output: Any) -> None:
        self.final_output = "" if output is None else str(output)

    def record_usage(
        self,
        *,
        input_tokens: int = 0,
        output_tokens: int = 0,
        cache_creation_input_tokens: int = 0,
        cache_read_input_tokens: int = 0,
    ) -> None:
        self.usage.input_tokens += input_tokens
        self.usage.output_tokens += output_tokens
        self.usage.cache_creation_input_tokens += cache_creation_input_tokens
        self.usage.cache_read_input_tokens += cache_read_input_tokens

    def record_error(self, error: BaseException | str) -> None:
        self.errors.append(str(error))

    def span(self, name: str, *, kind: str = "custom", input: Any = None, attributes: dict[str, Any] | None = None) -> SpanContext:
        return SpanContext(self, name=name, kind=kind, input=input, attributes=attributes or {})

    def tool_call(self, name: str, *, input: dict[str, Any] | None = None) -> ToolCallContext:
        return ToolCallContext(self, name=name, input=input or {})

    def start_span(self, name: str, *, kind: str = "custom", input: Any = None, attributes: dict[str, Any] | None = None) -> TraceSpan:
        span_id = _stable_id("span", self.trace_id, len(self.spans), name)
        span = TraceSpan(
            span_id=span_id,
            trace_id=self.trace_id,
            parent_span_id=self._span_stack[-1] if self._span_stack else None,
            name=name,
            kind=kind,
            start_time=None,
            status="unset",
            input=input,
            attributes=attributes or {},
        )
        self.spans.append(span)
        self._span_stack.append(span_id)
        return span

    def end_span(self, span: TraceSpan, *, output: Any = None, status: str = "ok") -> None:
        span.output = output
        span.status = status
        if span.latency_ms is None:
            span.latency_ms = 0
        if self._span_stack and self._span_stack[-1] == span.span_id:
            self._span_stack.pop()

    def fail_span(self, span: TraceSpan, error: BaseException | str) -> None:
        span.error = str(error)
        span.status = "error"
        if self._span_stack and self._span_stack[-1] == span.span_id:
            self._span_stack.pop()

    def to_trace(self) -> AgentTrace:
        metadata = dict(self.config.metadata)
        metadata.setdefault("instrumentation", {"sdk_language": "python", "sdk_version": "0.1.0", "schema_version": "agenteval.trace.v1"})
        trace = AgentTrace(
            trace_id=self.trace_id,
            case_id=self.config.case_id,
            session_id=self.config.session_id,
            user_id_hash=self.config.user_id_hash,
            agent_id=self.config.agent_id,
            agent_version=self.config.agent_version,
            source=self.config.source,
            input=self.input,
            final_output=self.final_output,
            messages=self.messages,
            spans=self.spans,
            tool_calls=self.tool_calls,
            usage=self.usage,
            latency_ms=(time.perf_counter() - self._started) * 1000 if self._started else 0,
            errors=self.errors,
            tags=self.config.tags,
            metadata=metadata,
        )
        return _redact_trace(trace, self.redactor) if self.config.redaction_enabled else trace

    def flush(self) -> None:
        self.writer.append(self.to_trace())

    def flush_safely(self) -> None:
        try:
            self.flush()
        except Exception:
            if self.config.fail_open:
                LOGGER.warning("AgentEval instrumentation failed to flush trace", exc_info=True)
                return
            raise


class SpanContext:
    def __init__(self, tracer: AgentEvalTracer, *, name: str, kind: str, input: Any, attributes: dict[str, Any]):
        self.tracer = tracer
        self.name = name
        self.kind = kind
        self.input = input
        self.attributes = attributes
        self.span: TraceSpan | None = None
        self._started = 0.0

    def __enter__(self) -> SpanContext:
        self._started = time.perf_counter()
        self.span = self.tracer.start_span(self.name, kind=self.kind, input=self.input, attributes=self.attributes)
        return self

    def __exit__(self, exc_type: type[BaseException] | None, exc: BaseException | None, traceback: TracebackType | None) -> bool:
        if self.span is None:
            return False
        self.span.latency_ms = (time.perf_counter() - self._started) * 1000
        if exc is not None:
            self.tracer.fail_span(self.span, exc)
        else:
            self.tracer.end_span(self.span, status="ok")
        return False

    async def __aenter__(self) -> SpanContext:
        return self.__enter__()

    async def __aexit__(self, exc_type: type[BaseException] | None, exc: BaseException | None, traceback: TracebackType | None) -> bool:
        return self.__exit__(exc_type, exc, traceback)

    def set_output(self, output: Any) -> None:
        if self.span is not None:
            self.span.output = output


class ToolCallContext:
    def __init__(self, tracer: AgentEvalTracer, *, name: str, input: dict[str, Any]):
        self.tracer = tracer
        self.name = name
        self.input = input
        self.call = ToolCall(name=name, input=input)
        self._span_context = tracer.span(name, kind="tool", input=input)

    def __enter__(self) -> ToolCallContext:
        self._span_context.__enter__()
        return self

    def __exit__(self, exc_type: type[BaseException] | None, exc: BaseException | None, traceback: TracebackType | None) -> bool:
        if exc is not None:
            self.set_error(exc)
        self.tracer.tool_calls.append(self.call)
        self._span_context.__exit__(exc_type, exc, traceback)
        return False

    async def __aenter__(self) -> ToolCallContext:
        return self.__enter__()

    async def __aexit__(self, exc_type: type[BaseException] | None, exc: BaseException | None, traceback: TracebackType | None) -> bool:
        return self.__exit__(exc_type, exc, traceback)

    def set_output(self, output: Any) -> None:
        self.call.output = output
        self._span_context.set_output(output)

    def set_error(self, error: BaseException | str) -> None:
        self.call.error = str(error)


def trace_agent_run(**config: Any) -> Callable[[Callable[P, T] | Callable[P, Awaitable[T]]], Callable[P, T] | Callable[P, Awaitable[T]]]:
    def decorator(func: Callable[P, T] | Callable[P, Awaitable[T]]) -> Callable[P, T] | Callable[P, Awaitable[T]]:
        if inspect.iscoroutinefunction(func):
            @functools.wraps(func)
            async def async_wrapper(*args: P.args, **kwargs: P.kwargs) -> T:
                async with AgentEvalTracer(**config) as tracer:
                    result = await func(*args, **kwargs)
                    tracer.set_final_output(result)
                    return result

            return async_wrapper

        @functools.wraps(func)
        def wrapper(*args: P.args, **kwargs: P.kwargs) -> T:
            with AgentEvalTracer(**config) as tracer:
                result = func(*args, **kwargs)
                tracer.set_final_output(result)
                return result

        return wrapper

    return decorator


def current_tracer() -> AgentEvalTracer:
    tracer = _CURRENT_TRACER.get()
    if tracer is None:
        raise RuntimeError("no active AgentEvalTracer")
    return tracer


def span(name: str, *, kind: str = "custom", input: Any = None, attributes: dict[str, Any] | None = None) -> SpanContext:
    return current_tracer().span(name, kind=kind, input=input, attributes=attributes)


def tool_call(name: str, *, input: dict[str, Any] | None = None) -> ToolCallContext:
    return current_tracer().tool_call(name, input=input)


def record_usage(**usage: int) -> None:
    current_tracer().record_usage(**usage)


def _redact_trace(trace: AgentTrace, redactor: Redactor | None) -> AgentTrace:
    payload = trace.model_dump()
    redacted = redact_value(payload, redactor=redactor)
    return AgentTrace.model_validate(redacted)


def _stable_id(prefix: str, *parts: Any) -> str:
    raw = "::".join(str(part) for part in parts)
    digest = hashlib.sha1(raw.encode("utf-8")).hexdigest()[:16]
    return f"{prefix}_{digest}"
