from __future__ import annotations

import json
import time
from typing import Any

import anthropic

from adapters.contract import adapter_metadata
from agents.anthropic_utils import case_messages, case_tools, extract_text, extract_usage, merge_usage
from config import AgentConfig
from schemas import AgentRun, ChatMessage, EvalCase, RunContext, ToolCall, Usage
from simulators import ScriptedUserSimulator
from tools import MockToolRuntime


class ClaudeAgentAdapter:
    """Claude adapter backed by the official Anthropic Python SDK."""

    def __init__(self, config: AgentConfig, client: Any | None = None):
        self.config = config
        self.client = client or anthropic.AsyncAnthropic()

    async def run(self, case: EvalCase, context: RunContext) -> AgentRun:
        if case.scenario.get("mode") == "dynamic":
            from runners.dynamic import DynamicScenarioRuntime

            return await DynamicScenarioRuntime(self).run(case, context)

        started = time.perf_counter()
        api_messages = [_message_to_api(message) for message in case_messages(case)]
        trace_messages = list(case_messages(case))
        scripted_turns = _scripted_turns(case)
        tools = case_tools(case)
        runtime = MockToolRuntime.from_case(case.scenario.get("tools"), initial_state=case.scenario.get("initial_state"))
        tool_calls: list[ToolCall] = []
        usage = Usage()
        raw_responses: list[dict[str, Any]] = []
        final_output = ""

        try:
            final_output, api_messages, trace_messages, turn_calls, turn_usage, turn_raw = await self._complete_turn(api_messages, trace_messages, tools, runtime)
            tool_calls.extend(turn_calls)
            usage = merge_usage(usage, turn_usage)
            raw_responses.extend(turn_raw)

            for user_turn in scripted_turns:
                api_messages.append({"role": "user", "content": user_turn})
                trace_messages.append(ChatMessage(role="user", content=user_turn))
                final_output, api_messages, trace_messages, turn_calls, turn_usage, turn_raw = await self._complete_turn(api_messages, trace_messages, tools, runtime)
                tool_calls.extend(turn_calls)
                usage = merge_usage(usage, turn_usage)
                raw_responses.extend(turn_raw)
        except (anthropic.APIError, RuntimeError) as exc:
            return AgentRun(
                case_id=case.id,
                messages=trace_messages,
                latency_ms=(time.perf_counter() - started) * 1000,
                errors=[f"{exc.__class__.__name__}: {exc}"],
                artifacts={"adapter": _anthropic_metadata(tool_calls)},
            )

        artifacts: dict[str, Any] = {"adapter": _anthropic_metadata(tool_calls)}
        if runtime.state:
            artifacts["final_state"] = runtime.state

        return AgentRun(
            case_id=case.id,
            messages=trace_messages,
            final_output=final_output,
            tool_calls=tool_calls,
            latency_ms=(time.perf_counter() - started) * 1000,
            usage=usage,
            raw_response={"responses": raw_responses},
            artifacts=artifacts,
        )

    async def complete_turn(
        self,
        messages: list[ChatMessage],
        tools: list[dict[str, Any]],
        context: RunContext,
        runtime: MockToolRuntime,
    ) -> tuple[str, list[ChatMessage], list[ToolCall], Usage, list[dict[str, Any]]]:
        api_messages = [_message_to_api(message) for message in messages]
        trace_messages = list(messages)
        final_output, _, trace_messages, tool_calls, usage, raw_responses = await self._complete_turn(api_messages, trace_messages, tools, runtime)
        return final_output, trace_messages, tool_calls, usage, raw_responses

    async def _complete_turn(
        self,
        api_messages: list[dict[str, Any]],
        trace_messages: list[ChatMessage],
        tools: list[dict[str, Any]],
        runtime: MockToolRuntime,
    ) -> tuple[str, list[dict[str, Any]], list[ChatMessage], list[ToolCall], Usage, list[dict[str, Any]]]:
        usage = Usage()
        tool_calls: list[ToolCall] = []
        raw_responses: list[dict[str, Any]] = []
        max_iterations = int(self.config.settings.get("max_tool_iterations", 8))

        for _ in range(max_iterations + 1):
            response = await self.client.messages.create(**self._build_request(api_messages, tools))
            usage = merge_usage(usage, extract_usage(response))
            raw_responses.append(_to_dict(response))
            if getattr(response, "stop_reason", None) == "refusal":
                details = getattr(response, "stop_details", None)
                category = getattr(details, "category", None) if details is not None else None
                explanation = getattr(details, "explanation", None) if details is not None else None
                message = "Anthropic response stopped with refusal"
                if category:
                    message += f" ({category})"
                if explanation:
                    message += f": {explanation}"
                raise RuntimeError(message)
            text = extract_text(response.content)
            tool_use_blocks = _extract_tool_use_blocks(response.content)
            if not tool_use_blocks:
                api_messages.append({"role": "assistant", "content": text})
                trace_messages.append(ChatMessage(role="assistant", content=text))
                return text, api_messages, trace_messages, tool_calls, usage, raw_responses

            api_messages.append({"role": "assistant", "content": response.content})
            if text:
                trace_messages.append(ChatMessage(role="assistant", content=text))
            tool_results = []
            pending_calls = [ToolCall(name=block["name"], input=block["input"]) for block in tool_use_blocks]
            applied_calls, _ = runtime.apply(pending_calls)
            for block, call in zip(tool_use_blocks, applied_calls, strict=True):
                tool_calls.append(call)
                result_content = json.dumps(call.output, ensure_ascii=False) if call.output is not None else ""
                if call.error:
                    result_content = call.error
                tool_result: dict[str, Any] = {
                    "type": "tool_result",
                    "tool_use_id": block["id"],
                    "content": result_content,
                }
                if call.error:
                    tool_result["is_error"] = True
                tool_results.append(tool_result)
            api_messages.append({"role": "user", "content": tool_results})

        raise RuntimeError(f"tool loop exceeded max_tool_iterations={max_iterations}")

    def _build_request(self, messages: list[dict[str, Any]], tools: list[dict[str, Any]] | None = None) -> dict[str, Any]:
        request: dict[str, Any] = {
            "model": self.config.model,
            "max_tokens": self.config.max_tokens,
            "messages": list(messages),
        }
        if tools:
            request["tools"] = tools

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

        # Fable 5 and Opus 4.8/4.7 reject temperature/top_p/top_k. Only pass temperature
        # when explicitly configured for models that support it.
        if self.config.temperature is not None and _model_allows_sampling(self.config.model):
            request["temperature"] = self.config.temperature

        if self.config.thinking:
            request["thinking"] = self.config.thinking
        if self.config.output_config:
            request["output_config"] = self.config.output_config

        return _sanitize_request_for_model(request)


def _model_allows_sampling(model: str) -> bool:
    normalized = str(model or "")
    if normalized in {"claude-fable-5", "claude-mythos-5"}:
        return False
    if normalized.startswith("claude-opus-4-7") or normalized.startswith("claude-opus-4-8"):
        return False
    return True


def _sanitize_request_for_model(request: dict[str, Any]) -> dict[str, Any]:
    model = str(request.get("model") or "")
    if not _model_allows_sampling(model):
        for key in ("temperature", "top_p", "top_k"):
            request.pop(key, None)
    thinking = request.get("thinking")
    if isinstance(thinking, dict):
        thinking_type = thinking.get("type")
        if model in {"claude-fable-5", "claude-mythos-5"}:
            if thinking_type == "adaptive":
                cleaned = {key: value for key, value in thinking.items() if key != "budget_tokens"}
                request["thinking"] = cleaned
            else:
                request.pop("thinking", None)
        elif model.startswith("claude-opus-4-7") or model.startswith("claude-opus-4-8"):
            if thinking_type == "enabled" or "budget_tokens" in thinking:
                cleaned = {key: value for key, value in thinking.items() if key != "budget_tokens"}
                cleaned["type"] = "adaptive"
                request["thinking"] = cleaned
    return request

def _anthropic_metadata(tool_calls: list[ToolCall]) -> dict[str, Any]:
    return adapter_metadata(
        "anthropic",
        framework="anthropic",
        framework_version=str(getattr(anthropic, "__version__", "unknown")),
        capabilities={"messages": True, "tool_calls": bool(tool_calls), "usage": True},
        lossiness=["Anthropic adapter records SDK responses and normalized tool calls but does not emit provider spans."],
    )


def _scripted_turns(case: EvalCase) -> list[str]:
    simulator = ScriptedUserSimulator.from_case(case)
    return simulator.turns if simulator else []


def _message_to_api(message: ChatMessage) -> dict[str, Any]:
    return {"role": message.role, "content": message.content}


def _extract_tool_use_blocks(content: list[Any]) -> list[dict[str, Any]]:
    calls: list[dict[str, Any]] = []
    for block in content:
        if getattr(block, "type", None) == "tool_use":
            calls.append(
                {
                    "id": getattr(block, "id", ""),
                    "name": getattr(block, "name", ""),
                    "input": getattr(block, "input", {}) or {},
                }
            )
    return calls


def _to_dict(response: Any) -> dict[str, Any]:
    if hasattr(response, "model_dump"):
        return response.model_dump(mode="json")
    if hasattr(response, "to_dict"):
        return response.to_dict()
    return {"repr": repr(response)}
