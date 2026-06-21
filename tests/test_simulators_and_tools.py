from types import SimpleNamespace

import asyncio

from agents.static_adapter import StaticAgentAdapter
from schemas import ChatMessage, EvalCase, ToolCall
from simulators import LLMUserSimulator, ScriptedUserSimulator
from tools import MockToolRuntime


class FakeMessages:
    def __init__(self, response):
        self.response = response
        self.requests = []

    async def create(self, **request):
        self.requests.append(request)
        return self.response


class FakeClient:
    def __init__(self, response):
        self.messages = FakeMessages(response)


def text_response(text: str):
    return SimpleNamespace(
        content=[SimpleNamespace(type="text", text=text)],
        usage=SimpleNamespace(input_tokens=7, output_tokens=8, cache_creation_input_tokens=0, cache_read_input_tokens=1),
    )


def test_scripted_user_simulator_builds_messages() -> None:
    case = EvalCase(id="c1", input="start", scenario={"user_simulator": {"type": "scripted", "turns": ["turn 1", "turn 2"]}})
    simulator = ScriptedUserSimulator.from_case(case)

    messages = simulator.messages(case.input)

    assert [message.content for message in messages] == ["start", "turn 1", "turn 2"]


def test_llm_user_simulator_builds_request_and_returns_usage() -> None:
    client = FakeClient(text_response("请继续处理"))
    simulator = LLMUserSimulator({"type": "llm", "persona": "angry customer", "goal": "refund", "hidden_facts": {"order_id": "A100"}}, client=client)

    result = asyncio.run(simulator.next_turn("需要确认", {"orders": {"A100": "paid"}}, [ChatMessage(role="user", content="我要退款")]))

    assert result["reply"] == "请继续处理"
    assert result["usage"].input_tokens == 7
    assert result["usage"].cache_read_input_tokens == 1
    request = client.messages.requests[0]
    assert request["model"] == "claude-opus-4-8"
    assert "angry customer" in request["messages"][0]["content"]
    assert result["artifact"]["type"] == "llm"


def test_llm_user_simulator_stop_phrase_returns_no_reply() -> None:
    client = FakeClient(text_response("DONE"))
    simulator = LLMUserSimulator({"type": "llm", "stop_phrases": ["done"]}, client=client)

    result = asyncio.run(simulator.next_turn("完成了吗", {}, []))

    assert result["reply"] is None
    assert result["artifact"]["stop"] is True


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
