from __future__ import annotations

from copy import deepcopy
from typing import Any

from evaluators.matching import get_path, value_matches
from schemas import AgentRun, ChatMessage, EvalCase, RunContext, ToolCall, Usage
from simulators import RuleBasedUserSimulator
from tools import MockToolRuntime


class DynamicScenarioRuntime:
    """Runs deterministic multi-turn scenarios with mock tools and stop conditions."""

    def __init__(self, adapter):
        self.adapter = adapter

    async def run(self, case: EvalCase, context: RunContext) -> AgentRun:
        messages = _case_messages(case)
        api_messages = list(messages)
        tools = _case_tools(case)
        runtime = MockToolRuntime.from_case(case.scenario.get("tools"), initial_state=case.scenario.get("initial_state"))
        simulator = RuleBasedUserSimulator.from_case(case)
        max_turns = int(case.scenario.get("max_turns", 1) or 1)
        all_tool_calls: list[ToolCall] = []
        usage = Usage()
        raw_responses: list[dict[str, Any]] = []
        turns: list[dict[str, Any]] = []
        state_history: list[dict[str, Any]] = []
        final_output = ""
        stop_reason: str | None = None

        for turn_index in range(max_turns):
            final_output, new_messages, turn_calls, turn_usage, turn_raw = await self.adapter.complete_turn(api_messages, tools, context, runtime)
            applied_calls, state = runtime.apply(turn_calls)
            all_tool_calls.extend(applied_calls)
            usage = _merge_usage(usage, turn_usage)
            raw_responses.extend(turn_raw)
            api_messages = list(new_messages)
            messages = list(new_messages)
            turns.append(
                {
                    "index": turn_index,
                    "assistant": final_output,
                    "tool_calls": [call.model_dump(mode="json") for call in applied_calls],
                }
            )
            state_history.append({"turn": turn_index, "state": deepcopy(state)})

            stop_reason = _stop_reason(case, final_output, applied_calls, state)
            if stop_reason:
                break
            if turn_index + 1 >= max_turns:
                stop_reason = "max_turns"
                break
            user_turn = simulator.next_turn(final_output, state) if simulator else None
            if not user_turn:
                stop_reason = "user_simulator_exhausted"
                break
            user_message = ChatMessage(role="user", content=user_turn)
            api_messages.append(user_message)
            messages.append(user_message)

        artifacts = {
            "final_state": runtime.state,
            "dynamic": {
                "turns": turns,
                "state_history": state_history,
                "stop_reason": stop_reason or "max_turns",
                "final_state": runtime.state,
            },
        }
        return AgentRun(
            case_id=case.id,
            messages=messages,
            final_output=final_output,
            tool_calls=all_tool_calls,
            usage=usage,
            raw_response={"responses": raw_responses},
            artifacts=artifacts,
        )


def _case_messages(case: EvalCase) -> list[ChatMessage]:
    if isinstance(case.input, str):
        return [ChatMessage(role="user", content=case.input)]
    return list(case.input)


def _case_tools(case: EvalCase) -> list[dict[str, Any]]:
    tools = []
    for tool in case.scenario.get("tools", []) or []:
        name = str(tool.get("name", ""))
        if not name:
            continue
        tools.append(
            {
                "name": name,
                "description": str(tool.get("description") or f"Mock tool {name}"),
                "input_schema": tool.get("input_schema") or {"type": "object", "properties": {}},
            }
        )
    return tools


def _stop_reason(case: EvalCase, output: str, tool_calls: list[ToolCall], state: dict[str, Any]) -> str | None:
    for condition in case.scenario.get("stop_conditions", []) or []:
        condition_type = condition.get("type")
        if condition_type == "output_contains" and str(condition.get("text", "")) in output:
            return "output_contains"
        if condition_type == "tool_called" and any(call.name == condition.get("name") for call in tool_calls):
            return "tool_called"
        if condition_type == "final_state_matches" and _state_matches(state, condition.get("state") or {}):
            return "final_state_matches"
    return None


def _state_matches(state: dict[str, Any], expected: dict[str, Any]) -> bool:
    for path, value in expected.items():
        exists, actual = get_path(state, str(path))
        if not exists or not value_matches(value, actual, "exact"):
            return False
    return True


def _merge_usage(left: Usage, right: Usage) -> Usage:
    return Usage(
        input_tokens=left.input_tokens + right.input_tokens,
        output_tokens=left.output_tokens + right.output_tokens,
        cache_creation_input_tokens=left.cache_creation_input_tokens + right.cache_creation_input_tokens,
        cache_read_input_tokens=left.cache_read_input_tokens + right.cache_read_input_tokens,
    )
