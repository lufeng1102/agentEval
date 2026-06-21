import asyncio
from types import SimpleNamespace

from config import AgentConfig
from agents.claude_adapter import ClaudeAgentAdapter
from agents.static_adapter import StaticAgentAdapter
from runners.dynamic import DynamicScenarioRuntime
from schemas import AgentRun, ChatMessage, EvalCase, RunContext, ToolCall, Usage


class FakeLLMUserSimulator:
    def __init__(self, replies):
        self.replies = list(replies)
        self.calls = 0

    async def next_turn(self, assistant_output, state, messages=None):
        self.calls += 1
        reply = self.replies.pop(0)
        return {
            "reply": reply,
            "usage": Usage(input_tokens=5, output_tokens=6),
            "artifact": {"type": "llm", "reply": reply, "turn_index": self.calls - 1},
        }


class ScriptedTurnAdapter:
    def __init__(self, turns: list[AgentRun]):
        self.turns = list(turns)
        self.calls = 0

    async def complete_turn(self, messages, tools, context, runtime):
        self.calls += 1
        turn = self.turns.pop(0)
        return turn.final_output, list(messages) + [ChatMessage(role="assistant", content=turn.final_output)], turn.tool_calls, turn.usage, [{"turn": self.calls}]


class FakeMessages:
    def __init__(self, responses):
        self.responses = list(responses)
        self.requests = []

    async def create(self, **request):
        self.requests.append(request)
        return self.responses.pop(0)


class FakeClient:
    def __init__(self, responses):
        self.messages = FakeMessages(responses)


def text_response(text: str):
    return SimpleNamespace(
        content=[SimpleNamespace(type="text", text=text)],
        usage=SimpleNamespace(input_tokens=1, output_tokens=2, cache_creation_input_tokens=0, cache_read_input_tokens=0),
        model_dump=lambda mode="json": {"content": [{"type": "text", "text": text}]},
    )


def tool_response(tool_id: str, name: str, tool_input: dict):
    return SimpleNamespace(
        content=[SimpleNamespace(type="tool_use", id=tool_id, name=name, input=tool_input)],
        usage=SimpleNamespace(input_tokens=3, output_tokens=4, cache_creation_input_tokens=0, cache_read_input_tokens=0),
        model_dump=lambda mode="json": {"content": [{"type": "tool_use", "id": tool_id, "name": name, "input": tool_input}]},
    )


def test_dynamic_runtime_uses_llm_user_simulator(monkeypatch, tmp_path) -> None:
    simulator = FakeLLMUserSimulator(["继续"])
    monkeypatch.setattr("runners.dynamic.build_user_simulator", lambda case: simulator)
    adapter = ScriptedTurnAdapter([AgentRun(case_id="c1", final_output="第一轮"), AgentRun(case_id="c1", final_output="完成")])
    case = EvalCase(id="c1", input="开始", scenario={"mode": "dynamic", "max_turns": 2, "user_simulator": {"type": "llm"}, "stop_conditions": [{"type": "output_contains", "text": "完成"}]})

    run = asyncio.run(DynamicScenarioRuntime(adapter).run(case, RunContext(output_dir=tmp_path)))

    assert [message.role for message in run.messages] == ["user", "assistant", "user", "assistant"]
    assert run.messages[2].content == "继续"
    assert run.usage.input_tokens == 5
    assert run.usage.output_tokens == 6
    assert run.artifacts["dynamic"]["simulator_turns"][0]["type"] == "llm"
    assert run.artifacts["dynamic"]["stop_reason"] == "output_contains"


def test_dynamic_runtime_stops_when_llm_user_simulator_returns_empty(monkeypatch, tmp_path) -> None:
    simulator = FakeLLMUserSimulator([""])
    monkeypatch.setattr("runners.dynamic.build_user_simulator", lambda case: simulator)
    adapter = ScriptedTurnAdapter([AgentRun(case_id="c1", final_output="需要继续")])
    case = EvalCase(id="c1", input="开始", scenario={"mode": "dynamic", "max_turns": 3, "user_simulator": {"type": "llm"}})

    run = asyncio.run(DynamicScenarioRuntime(adapter).run(case, RunContext(output_dir=tmp_path)))

    assert run.artifacts["dynamic"]["stop_reason"] == "user_simulator_exhausted"
    assert run.artifacts["dynamic"]["simulator_turns"][0]["reply"] == ""
    assert adapter.calls == 1

def test_dynamic_runtime_stops_when_final_state_matches(tmp_path) -> None:
    adapter = ScriptedTurnAdapter(
        [
            AgentRun(case_id="c1", final_output="我先取消订单", tool_calls=[ToolCall(name="order_cancel", input={"order_id": "A100"})]),
        ]
    )
    case = EvalCase(
        id="c1",
        input="取消订单 A100",
        scenario={
            "mode": "dynamic",
            "initial_state": {"orders": {"A100": {"status": "paid"}}},
            "tools": [
                {
                    "name": "order_cancel",
                    "input_schema": {"type": "object", "required": ["order_id"], "properties": {"order_id": {"type": "string"}}},
                    "state_updates": [{"path": "orders.${input.order_id}.status", "value": "cancelled"}],
                    "mock_output": {"ok": True},
                }
            ],
            "stop_conditions": [{"type": "final_state_matches", "state": {"orders.A100.status": "cancelled"}}],
        },
    )

    run = asyncio.run(DynamicScenarioRuntime(adapter).run(case, RunContext(output_dir=tmp_path)))

    assert run.final_output == "我先取消订单"
    assert run.tool_calls[0].output == {"ok": True}
    assert run.artifacts["final_state"]["orders"]["A100"]["status"] == "cancelled"
    assert run.artifacts["dynamic"]["stop_reason"] == "final_state_matches"
    assert len(run.artifacts["dynamic"]["state_history"]) == 1


def test_dynamic_runtime_uses_rule_based_user_until_output_stop(tmp_path) -> None:
    adapter = ScriptedTurnAdapter(
        [
            AgentRun(case_id="c1", final_output="需要确认取消吗？"),
            AgentRun(case_id="c1", final_output="已完成取消"),
        ]
    )
    case = EvalCase(
        id="c1",
        input="取消订单",
        scenario={
            "mode": "dynamic",
            "max_turns": 3,
            "user_simulator": {
                "type": "rule_based",
                "rules": [{"when": {"output_contains": "确认"}, "reply": "确认取消"}],
            },
            "stop_conditions": [{"type": "output_contains", "text": "已完成"}],
        },
    )

    run = asyncio.run(DynamicScenarioRuntime(adapter).run(case, RunContext(output_dir=tmp_path)))

    assert [message.role for message in run.messages] == ["user", "assistant", "user", "assistant"]
    assert run.messages[2].content == "确认取消"
    assert run.artifacts["dynamic"]["stop_reason"] == "output_contains"
    assert adapter.calls == 2


def test_dynamic_runtime_stops_at_max_turns(tmp_path) -> None:
    adapter = ScriptedTurnAdapter([AgentRun(case_id="c1", final_output="还没好"), AgentRun(case_id="c1", final_output="仍未完成")])
    case = EvalCase(
        id="c1",
        input="开始",
        scenario={
            "mode": "dynamic",
            "max_turns": 1,
            "user_simulator": {"type": "rule_based", "rules": [{"when": {"output_contains": "还没"}, "reply": "继续"}]},
        },
    )

    run = asyncio.run(DynamicScenarioRuntime(adapter).run(case, RunContext(output_dir=tmp_path)))

    assert run.final_output == "还没好"
    assert run.artifacts["dynamic"]["stop_reason"] == "max_turns"
    assert adapter.calls == 1


def test_dynamic_tool_output_can_read_state(tmp_path) -> None:
    adapter = ScriptedTurnAdapter([AgentRun(case_id="c1", final_output="查询中", tool_calls=[ToolCall(name="order_lookup", input={"order_id": "A100"})])])
    case = EvalCase(
        id="c1",
        input="查订单",
        scenario={
            "mode": "dynamic",
            "initial_state": {"orders": {"A100": {"status": "paid"}}},
            "tools": [{"name": "order_lookup", "dynamic_output": {"type": "state_lookup", "path": "orders.${input.order_id}"}}],
            "stop_conditions": [{"type": "tool_called", "name": "order_lookup"}],
        },
    )

    run = asyncio.run(DynamicScenarioRuntime(adapter).run(case, RunContext(output_dir=tmp_path)))

    assert run.tool_calls[0].output == {"status": "paid"}
    assert run.artifacts["dynamic"]["stop_reason"] == "tool_called"




def test_claude_adapter_runs_dynamic_scenario_with_fake_tool_loop(tmp_path) -> None:
    client = FakeClient([tool_response("toolu_1", "order_cancel", {"order_id": "A100"}), text_response("已取消")])
    adapter = ClaudeAgentAdapter(AgentConfig(provider="anthropic"), client=client)
    case = EvalCase(
        id="c1",
        input="取消订单",
        scenario={
            "mode": "dynamic",
            "max_turns": 1,
            "initial_state": {"orders": {"A100": {"status": "paid"}}},
            "tools": [
                {
                    "name": "order_cancel",
                    "input_schema": {"type": "object", "required": ["order_id"], "properties": {"order_id": {"type": "string"}}},
                    "state_updates": [{"path": "orders.${input.order_id}.status", "value": "cancelled"}],
                    "mock_output": {"ok": True},
                }
            ],
            "stop_conditions": [{"type": "final_state_matches", "state": {"orders.A100.status": "cancelled"}}],
        },
    )

    run = asyncio.run(adapter.run(case, RunContext(output_dir=tmp_path)))

    assert run.artifacts["dynamic"]["stop_reason"] == "final_state_matches"
    assert run.artifacts["final_state"]["orders"]["A100"]["status"] == "cancelled"
    assert client.messages.requests[0]["tools"][0]["name"] == "order_cancel"
    assert client.messages.requests[1]["messages"][-1]["content"][0]["type"] == "tool_result"


def test_rule_based_user_uses_state_matches(tmp_path) -> None:
    adapter = ScriptedTurnAdapter([AgentRun(case_id="c1", final_output="状态已变更", tool_calls=[ToolCall(name="order_cancel", input={"order_id": "A100"})]), AgentRun(case_id="c1", final_output="收到确认")])
    case = EvalCase(
        id="c1",
        input="取消订单",
        scenario={
            "mode": "dynamic",
            "max_turns": 2,
            "initial_state": {"orders": {"A100": {"status": "paid"}}},
            "tools": [{"name": "order_cancel", "state_updates": [{"path": "orders.${input.order_id}.status", "value": "cancelled"}]}],
            "user_simulator": {"type": "rule_based", "rules": [{"when": {"state_matches": {"orders.A100.status": "cancelled"}}, "reply": "我看到了取消状态"}]},
        },
    )

    run = asyncio.run(DynamicScenarioRuntime(adapter).run(case, RunContext(output_dir=tmp_path)))

    assert run.messages[2].content == "我看到了取消状态"
    assert adapter.calls == 2


def test_dynamic_runtime_stops_when_user_simulator_missing(tmp_path) -> None:
    adapter = ScriptedTurnAdapter([AgentRun(case_id="c1", final_output="需要继续")])
    case = EvalCase(id="c1", input="开始", scenario={"mode": "dynamic", "max_turns": 3})

    run = asyncio.run(DynamicScenarioRuntime(adapter).run(case, RunContext(output_dir=tmp_path)))

    assert run.artifacts["dynamic"]["stop_reason"] == "user_simulator_exhausted"
    assert adapter.calls == 1


def test_dynamic_runtime_stops_when_no_user_rule_matches(tmp_path) -> None:
    adapter = ScriptedTurnAdapter([AgentRun(case_id="c1", final_output="没有匹配")])
    case = EvalCase(id="c1", input="开始", scenario={"mode": "dynamic", "max_turns": 3, "user_simulator": {"type": "rule_based", "rules": [{"when": {"output_contains": "确认"}, "reply": "确认"}]}})

    run = asyncio.run(DynamicScenarioRuntime(adapter).run(case, RunContext(output_dir=tmp_path)))

    assert run.artifacts["dynamic"]["stop_reason"] == "user_simulator_exhausted"
    assert adapter.calls == 1


def test_dynamic_tool_state_lookup_missing_path_returns_none(tmp_path) -> None:
    adapter = ScriptedTurnAdapter([AgentRun(case_id="c1", final_output="查询", tool_calls=[ToolCall(name="order_lookup", input={"order_id": "missing"})])])
    case = EvalCase(
        id="c1",
        input="查询",
        scenario={"mode": "dynamic", "initial_state": {"orders": {}}, "tools": [{"name": "order_lookup", "dynamic_output": {"type": "state_lookup", "path": "orders.${input.order_id}"}}], "stop_conditions": [{"type": "tool_called", "name": "order_lookup"}]},
    )

    run = asyncio.run(DynamicScenarioRuntime(adapter).run(case, RunContext(output_dir=tmp_path)))

    assert run.tool_calls[0].output is None
    assert run.artifacts["dynamic"]["stop_reason"] == "tool_called"


def test_dynamic_runtime_merges_usage_across_turns(tmp_path) -> None:
    adapter = ScriptedTurnAdapter(
        [
            AgentRun(case_id="c1", final_output="第一轮", usage=Usage(input_tokens=1, output_tokens=2, cache_creation_input_tokens=3, cache_read_input_tokens=4)),
            AgentRun(case_id="c1", final_output="第二轮", usage=Usage(input_tokens=10, output_tokens=20, cache_creation_input_tokens=30, cache_read_input_tokens=40)),
        ]
    )
    case = EvalCase(id="c1", input="开始", scenario={"mode": "dynamic", "max_turns": 2, "user_simulator": {"type": "rule_based", "rules": [{"when": {"output_contains": "第一轮"}, "reply": "继续"}]}})

    run = asyncio.run(DynamicScenarioRuntime(adapter).run(case, RunContext(output_dir=tmp_path)))

    assert run.usage.input_tokens == 11
    assert run.usage.output_tokens == 22
    assert run.usage.cache_creation_input_tokens == 33
    assert run.usage.cache_read_input_tokens == 44


def test_dynamic_stop_conditions_use_config_order(tmp_path) -> None:
    def run_with_conditions(conditions):
        adapter = ScriptedTurnAdapter([AgentRun(case_id="c1", final_output="已完成", tool_calls=[ToolCall(name="order_cancel", input={"order_id": "A100"})])])
        case = EvalCase(
            id="c1",
            input="取消",
            scenario={
                "mode": "dynamic",
                "initial_state": {"orders": {"A100": {"status": "paid"}}},
                "tools": [{"name": "order_cancel", "state_updates": [{"path": "orders.${input.order_id}.status", "value": "cancelled"}]}],
                "stop_conditions": conditions,
            },
        )
        return asyncio.run(DynamicScenarioRuntime(adapter).run(case, RunContext(output_dir=tmp_path))).artifacts["dynamic"]["stop_reason"]

    assert run_with_conditions([{"type": "tool_called", "name": "order_cancel"}, {"type": "final_state_matches", "state": {"orders.A100.status": "cancelled"}}]) == "tool_called"
    assert run_with_conditions([{"type": "final_state_matches", "state": {"orders.A100.status": "cancelled"}}, {"type": "tool_called", "name": "order_cancel"}]) == "final_state_matches"


def test_static_adapter_runs_dynamic_scenario(tmp_path) -> None:
    adapter = StaticAgentAdapter("已取消", tool_calls=[ToolCall(name="order_cancel", input={"order_id": "A100"})])
    case = EvalCase(
        id="c1",
        input="取消订单",
        scenario={
            "mode": "dynamic",
            "initial_state": {"orders": {"A100": {"status": "paid"}}},
            "tools": [{"name": "order_cancel", "state_updates": [{"path": "orders.${input.order_id}.status", "value": "cancelled"}]}],
            "stop_conditions": [{"type": "final_state_matches", "state": {"orders.A100.status": "cancelled"}}],
        },
    )

    run = asyncio.run(adapter.run(case, RunContext(output_dir=tmp_path)))

    assert run.final_output == "已取消"
    assert run.artifacts["dynamic"]["stop_reason"] == "final_state_matches"
    assert run.artifacts["final_state"]["orders"]["A100"]["status"] == "cancelled"
