from __future__ import annotations

import time
from typing import Any

import anthropic

from config import AgentConfig
from schemas import AgentRun, ChatMessage, EvalCase, RunContext, Usage


class ClaudeAgentAdapter:
    """Claude adapter backed by the official Anthropic Python SDK."""

    def __init__(self, config: AgentConfig):
        self.config = config
        self.client = anthropic.AsyncAnthropic()

    async def run(self, case: EvalCase, context: RunContext) -> AgentRun:
        messages = _case_messages(case)
        request = self._build_request(messages)
        started = time.perf_counter()

        try:
            response = await self.client.messages.create(**request)
        except anthropic.APIError as exc:
            return AgentRun(
                case_id=case.id,
                messages=messages,
                latency_ms=(time.perf_counter() - started) * 1000,
                errors=[f"{exc.__class__.__name__}: {exc}"],
            )

        return AgentRun(
            case_id=case.id,
            messages=messages,
            final_output=_extract_text(response.content),
            tool_calls=_extract_tool_calls(response.content),
            latency_ms=(time.perf_counter() - started) * 1000,
            usage=_extract_usage(response),
            raw_response=_to_dict(response),
        )

    def _build_request(self, messages: list[ChatMessage]) -> dict[str, Any]:
        request: dict[str, Any] = {
            "model": self.config.model,
            "max_tokens": self.config.max_tokens,
            "messages": [_message_to_api(message) for message in messages],
        }

        if self.config.system:
            if self.config.cache_system_prompt:
                request["system"] = [
                    {
                        "type": "text",
                        "text": self.config.system,
                        "cache_control": self.config.cache_control or {"type": "ephemeral"},
                    }
                ]
            else:
                request["system"] = self.config.system

        if self.config.cache_control and not self.config.cache_system_prompt:
            request["cache_control"] = self.config.cache_control

        # Opus 4.8/4.7 reject temperature/top_p/top_k. Only pass temperature
        # when explicitly configured for models that support it.
        if self.config.temperature is not None and not self.config.model.startswith("claude-opus-4-"):
            request["temperature"] = self.config.temperature

        if self.config.thinking:
            request["thinking"] = self.config.thinking
        if self.config.output_config:
            request["output_config"] = self.config.output_config

        return request


def _case_messages(case: EvalCase) -> list[ChatMessage]:
    if isinstance(case.input, str):
        return [ChatMessage(role="user", content=case.input)]
    return list(case.input)


def _message_to_api(message: ChatMessage) -> dict[str, Any]:
    return {"role": message.role, "content": message.content}


def _extract_text(content: list[Any]) -> str:
    parts: list[str] = []
    for block in content:
        if getattr(block, "type", None) == "text":
            parts.append(getattr(block, "text", ""))
    return "".join(parts).strip()


def _extract_tool_calls(content: list[Any]) -> list[dict[str, Any]]:
    calls: list[dict[str, Any]] = []
    for block in content:
        if getattr(block, "type", None) == "tool_use":
            calls.append(
                {
                    "name": getattr(block, "name", ""),
                    "input": getattr(block, "input", {}) or {},
                }
            )
    return calls


def _extract_usage(response: Any) -> Usage:
    usage = getattr(response, "usage", None)
    if usage is None:
        return Usage()
    return Usage(
        input_tokens=getattr(usage, "input_tokens", 0) or 0,
        output_tokens=getattr(usage, "output_tokens", 0) or 0,
        cache_creation_input_tokens=getattr(usage, "cache_creation_input_tokens", 0) or 0,
        cache_read_input_tokens=getattr(usage, "cache_read_input_tokens", 0) or 0,
    )


def _to_dict(response: Any) -> dict[str, Any]:
    if hasattr(response, "model_dump"):
        return response.model_dump(mode="json")
    if hasattr(response, "to_dict"):
        return response.to_dict()
    return {"repr": repr(response)}
