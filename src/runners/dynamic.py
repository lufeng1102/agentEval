from __future__ import annotations

from copy import deepcopy
from typing import Any

from agents.anthropic_utils import case_messages, case_tools, merge_usage
from evaluators.matching import get_path, value_matches
from schemas import AgentRun, ChatMessage, EvalCase, RunContext, ToolCall, Usage
from simulators import build_user_simulator, next_simulated_turn
from tools import MockToolRuntime


class DynamicScenarioRuntime:
    """Runs deterministic multi-turn scenarios with mock tools and stop conditions."""

    def __init__(self, adapter):
        self.adapter = adapter

    async def run(self, case: EvalCase, context: RunContext) -> AgentRun:
        messages = case_messages(case)
        api_messages = list(messages)
        tools = case_tools(case)
        runtime = MockToolRuntime.from_case(case.scenario.get("tools"), initial_state=case.scenario.get("initial_state"))
        simulator = build_user_simulator(case)
        max_turns = int(case.scenario.get("max_turns", 1) or 1)
        all_tool_calls: list[ToolCall] = []
        usage = Usage()
        raw_responses: list[dict[str, Any]] = []
        turns: list[dict[str, Any]] = []
        simulator_turns: list[dict[str, Any]] = []
        state_history: list[dict[str, Any]] = []
        final_output = ""
        stop_reason: str | None = None

        for turn_index in range(max_turns):
            final_output, new_messages, turn_calls, turn_usage, turn_raw = await self.adapter.complete_turn(api_messages, tools, context, runtime)
            applied_calls, state = runtime.apply(turn_calls)
            all_tool_calls.extend(applied_calls)
            usage = merge_usage(usage, turn_usage)
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
            simulated = await next_simulated_turn(simulator, final_output, state, messages)
            user_turn = simulated.get("reply")
            usage = merge_usage(usage, simulated.get("usage") or Usage())
            if simulated.get("artifact"):
                simulator_turns.append(simulated["artifact"])
            if user_turn is None or user_turn == "":
                stop_reason = "user_simulator_exhausted"
                break
            user_message = ChatMessage(role="user", content=str(user_turn))
            api_messages.append(user_message)
            messages.append(user_message)

        artifacts = {
            "final_state": runtime.state,
            "dynamic": {
                "turns": turns,
                "simulator_turns": simulator_turns,
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
