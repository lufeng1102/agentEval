from __future__ import annotations

import time
from typing import Any

from schemas import AgentRun, ChatMessage, EvalCase, RunContext, ToolCall, Usage
from simulators import ScriptedUserSimulator
from tools import MockToolRuntime


class StaticAgentAdapter:
    """Deterministic adapter for local smoke tests."""

    def __init__(self, response: str, tool_calls: list[ToolCall] | None = None, latency_ms: float | None = None, artifacts: dict[str, Any] | None = None):
        self.response = response
        self.tool_calls = tool_calls or []
        self.latency_ms = latency_ms
        self.artifacts = artifacts or {}

    async def run(self, case: EvalCase, context: RunContext) -> AgentRun:
        if case.scenario.get("mode") == "dynamic":
            from runners.dynamic import DynamicScenarioRuntime

            return await DynamicScenarioRuntime(self).run(case, context)

        started = time.perf_counter()
        messages = _case_messages(case)
        simulator = ScriptedUserSimulator.from_case(case)
        if simulator:
            messages = simulator.messages(case.input)
        runtime = MockToolRuntime.from_case(case.scenario.get("tools"), initial_state=case.scenario.get("initial_state"))
        tool_calls, runtime_state = runtime.apply(list(self.tool_calls))
        artifacts = dict(self.artifacts)
        if runtime_state:
            artifacts["final_state"] = runtime_state
        measured_latency = (time.perf_counter() - started) * 1000
        usage = Usage.model_validate(artifacts.pop("usage", {})) if "usage" in artifacts else Usage()
        return AgentRun(
            case_id=case.id,
            messages=messages,
            final_output=self.response,
            tool_calls=tool_calls,
            latency_ms=self.latency_ms if self.latency_ms is not None else measured_latency,
            usage=usage,
            artifacts=artifacts,
        )

    async def complete_turn(
        self,
        messages: list[ChatMessage],
        tools: list[dict[str, Any]],
        context: RunContext,
        runtime: MockToolRuntime,
    ) -> tuple[str, list[ChatMessage], list[ToolCall], Usage, list[dict[str, Any]]]:
        return self.response, [*messages, ChatMessage(role="assistant", content=self.response)], list(self.tool_calls), Usage(), []


def _case_messages(case: EvalCase) -> list[ChatMessage]:
    if isinstance(case.input, str):
        return [ChatMessage(role="user", content=case.input)]
    return list(case.input)
