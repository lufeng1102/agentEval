import asyncio

from agents.static_adapter import StaticAgentAdapter
from schemas import EvalCase, ToolCall
from simulators import ScriptedUserSimulator
from tools import MockToolRuntime


def test_scripted_user_simulator_builds_messages() -> None:
    case = EvalCase(id="c1", input="start", scenario={"user_simulator": {"type": "scripted", "turns": ["turn 1", "turn 2"]}})
    simulator = ScriptedUserSimulator.from_case(case)

    messages = simulator.messages(case.input)

    assert [message.content for message in messages] == ["start", "turn 1", "turn 2"]


def test_mock_tool_runtime_applies_outputs() -> None:
    runtime = MockToolRuntime([{"name": "lookup", "mock_output": {"status": "ok"}}])

    calls, state = runtime.apply([ToolCall(name="lookup"), ToolCall(name="other", output="x")])

    assert calls[0].output == {"status": "ok"}
    assert calls[1].output == "x"


def test_mock_tool_runtime_validates_input_and_updates_state() -> None:
    runtime = MockToolRuntime(
        [
            {
                "name": "cancel",
                "input_schema": {"type": "object", "required": ["order_id"], "properties": {"order_id": {"type": "string"}}},
                "state_updates": [{"path": "orders.${input.order_id}.status", "value": "cancelled"}],
            }
        ],
        initial_state={"orders": {"A100": {"status": "paid"}}},
    )

    calls, state = runtime.apply([ToolCall(name="cancel", input={"order_id": "A100"})])

    assert calls[0].error is None
    assert state["orders"]["A100"]["status"] == "cancelled"


def test_mock_tool_runtime_records_schema_errors() -> None:
    runtime = MockToolRuntime([{"name": "cancel", "input_schema": {"type": "object", "required": ["order_id"]}}])

    calls, state = runtime.apply([ToolCall(name="cancel", input={})])

    assert "required property" in calls[0].error


def test_static_adapter_uses_scripted_user_and_mock_tools() -> None:
    case = EvalCase(
        id="c1",
        input="start",
        scenario={
            "user_simulator": {"type": "scripted", "turns": ["confirm"]},
            "tools": [{"name": "lookup", "mock_output": {"status": "ok"}}],
        },
    )
    adapter = StaticAgentAdapter("done", tool_calls=[ToolCall(name="lookup")])

    run = asyncio.run(adapter.run(case, context=None))

    assert [message.content for message in run.messages] == ["start", "confirm"]
    assert run.tool_calls[0].output == {"status": "ok"}
