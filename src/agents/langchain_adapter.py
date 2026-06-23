from __future__ import annotations

import asyncio
import importlib
import inspect
import time
from typing import Any

from adapters.contract import adapter_metadata
from config import AgentConfig
from schemas import AgentRun, ChatMessage, EvalCase, RunContext, ToolCall, TraceSpan


class LangChainAgentAdapter:
    """Adapter for LangChain-compatible runnables without a hard LangChain dependency."""

    def __init__(self, config: AgentConfig):
        self.config = config
        self.runnable = _load_runnable(config)
        self.input_key = str(config.settings.get("input_key", "input"))
        self.output_key = str(config.settings.get("output_key", "output"))

    async def run(self, case: EvalCase, context: RunContext) -> AgentRun:
        started = time.perf_counter()
        payload = self._payload(case)
        errors: list[str] = []
        raw_response: Any = None
        try:
            raw_response = await self._invoke(payload)
        except Exception as exc:
            errors.append(str(exc))
        output = self._output(raw_response) if raw_response is not None else ""
        tool_calls = self._tool_calls(raw_response)
        spans = self._spans(raw_response, tool_calls)
        return AgentRun(
            case_id=case.id,
            messages=_case_messages(case),
            final_output=output,
            tool_calls=tool_calls,
            spans=spans,
            latency_ms=(time.perf_counter() - started) * 1000,
            errors=errors,
            raw_response=_jsonable(raw_response),
            artifacts={
                "adapter": adapter_metadata(
                    "langchain",
                    framework="langchain",
                    framework_version=str(self.config.settings.get("framework_version", "unknown")),
                    capabilities={"messages": True, "tool_calls": bool(tool_calls), "spans": bool(spans), "usage": False, "retrieval": _has_retrieval(spans)},
                    lossiness=["LangChain callback internals are captured only when the runnable returns intermediate_steps or spans."],
                )
            },
        )

    async def _invoke(self, payload: Any) -> Any:
        if hasattr(self.runnable, "ainvoke"):
            return await self.runnable.ainvoke(payload)
        if hasattr(self.runnable, "invoke"):
            return await asyncio.to_thread(self.runnable.invoke, payload)
        if inspect.iscoroutinefunction(self.runnable):
            return await self.runnable(payload)
        if callable(self.runnable):
            return await asyncio.to_thread(self.runnable, payload)
        raise TypeError("LangChain adapter requires a callable, invoke(), or ainvoke() runnable")

    def _payload(self, case: EvalCase) -> Any:
        user_input = case.input if isinstance(case.input, str) else [message.model_dump(mode="json") for message in case.input]
        if self.config.settings.get("raw_input"):
            return user_input
        extra = self.config.settings.get("invoke_kwargs") or {}
        return {self.input_key: user_input, **extra}

    def _output(self, response: Any) -> str:
        if isinstance(response, dict):
            for key in [self.output_key, "output", "result", "answer", "content"]:
                if key in response:
                    return _stringify(response[key])
        if hasattr(response, "content"):
            return _stringify(response.content)
        return _stringify(response)

    def _tool_calls(self, response: Any) -> list[ToolCall]:
        steps = _response_get(response, "intermediate_steps") or _response_get(response, "steps") or []
        calls = []
        for index, step in enumerate(steps):
            name, tool_input, output, error = _step_parts(step, index)
            calls.append(ToolCall(name=name, input=tool_input, output=output, error=error))
        for item in _response_get(response, "tool_calls") or []:
            if isinstance(item, ToolCall):
                calls.append(item)
            elif isinstance(item, dict):
                calls.append(ToolCall(name=str(item.get("name") or item.get("tool") or "tool"), input=_dict_or_raw(item.get("input") or item.get("args") or {}), output=item.get("output"), error=item.get("error")))
        return calls

    def _spans(self, response: Any, tool_calls: list[ToolCall]) -> list[TraceSpan]:
        spans_payload = _response_get(response, "spans") or []
        spans = []
        for index, item in enumerate(spans_payload):
            if isinstance(item, TraceSpan):
                spans.append(item)
            elif isinstance(item, dict):
                spans.append(TraceSpan(span_id=str(item.get("span_id") or f"langchain_span_{index}"), parent_span_id=item.get("parent_span_id"), name=str(item.get("name") or "langchain.span"), kind=str(item.get("kind") or "chain"), latency_ms=item.get("latency_ms"), status=item.get("status") or "unset", input=item.get("input"), output=item.get("output"), error=item.get("error"), attributes=item.get("attributes") or {}))
        if not spans:
            spans.append(TraceSpan(span_id="langchain_root", name="langchain.invoke", kind="chain", status="error" if _response_get(response, "error") else "ok"))
        for index, call in enumerate(tool_calls):
            if not any(span.kind == "tool" and span.name == call.name for span in spans):
                spans.append(TraceSpan(span_id=f"langchain_tool_{index}", parent_span_id=spans[0].span_id, name=call.name, kind="tool", status="error" if call.error else "ok", input=call.input, output=call.output, error=call.error, attributes={"source": "intermediate_steps"}))
        return spans


def _load_runnable(config: AgentConfig) -> Any:
    import_path = config.settings.get("import_path") or config.settings.get("path")
    if not import_path:
        raise ValueError("langchain agent requires agent.settings.import_path")
    module_name, _, attr = str(import_path).rpartition(".")
    if not module_name or not attr:
        raise ValueError(f"invalid langchain import path: {import_path}")
    factory = getattr(importlib.import_module(module_name), attr)
    try:
        return factory(config)
    except TypeError:
        return factory()


def _case_messages(case: EvalCase) -> list[ChatMessage]:
    if isinstance(case.input, str):
        return [ChatMessage(role="user", content=case.input)]
    return list(case.input)


def _response_get(response: Any, key: str) -> Any:
    if isinstance(response, dict):
        return response.get(key)
    return getattr(response, key, None)


def _step_parts(step: Any, index: int) -> tuple[str, dict[str, Any], Any, str | None]:
    if isinstance(step, dict):
        return str(step.get("tool") or step.get("name") or f"tool_{index}"), _dict_or_raw(step.get("input") or step.get("tool_input") or {}), step.get("output") or step.get("observation"), step.get("error")
    if isinstance(step, (list, tuple)) and len(step) >= 2:
        action, observation = step[0], step[1]
        return str(getattr(action, "tool", None) or getattr(action, "name", None) or f"tool_{index}"), _dict_or_raw(getattr(action, "tool_input", {})), observation, None
    return f"tool_{index}", {}, step, None


def _dict_or_raw(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {"raw": value}


def _stringify(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    return str(value)


def _jsonable(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, dict):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_jsonable(item) for item in value]
    if isinstance(value, tuple):
        return [_jsonable(item) for item in value]
    return str(value)


def _has_retrieval(spans: list[TraceSpan]) -> bool:
    return any(str(span.kind) == "retrieval" for span in spans)
