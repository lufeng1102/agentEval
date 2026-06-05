import asyncio
from types import SimpleNamespace

from agents.claude_adapter import ClaudeAgentAdapter
from config import AgentConfig
from schemas import EvalCase


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
        stop_reason="end_turn",
        usage=SimpleNamespace(input_tokens=1, output_tokens=2, cache_creation_input_tokens=0, cache_read_input_tokens=0),
        model_dump=lambda mode="json": {"content": [{"type": "text", "text": text}], "stop_reason": "end_turn"},
    )


def tool_response(tool_id: str, name: str, tool_input: dict):
    return SimpleNamespace(
        content=[SimpleNamespace(type="tool_use", id=tool_id, name=name, input=tool_input)],
        stop_reason="tool_use",
        usage=SimpleNamespace(input_tokens=3, output_tokens=4, cache_creation_input_tokens=0, cache_read_input_tokens=0),
        model_dump=lambda mode="json": {"content": [{"type": "tool_use", "id": tool_id, "name": name, "input": tool_input}], "stop_reason": "tool_use"},
    )


def test_claude_adapter_executes_mock_tool_loop() -> None:
    client = FakeClient([tool_response("toolu_1", "weather", {"city": "北京"}), text_response("北京晴，适合出行。")])
    adapter = ClaudeAgentAdapter(AgentConfig(provider="anthropic"), client=client)
    case = EvalCase(
        id="weather_001",
        input="查北京天气",
        scenario={"tools": [{"name": "weather", "input_schema": {"type": "object", "properties": {"city": {"type": "string"}}}, "mock_output": {"city": "北京", "condition": "晴"}}]},
    )

    run = asyncio.run(adapter.run(case, context=None))

    assert run.final_output == "北京晴，适合出行。"
    assert run.tool_calls[0].name == "weather"
    assert run.tool_calls[0].output == {"city": "北京", "condition": "晴"}
    assert len(client.messages.requests) == 2
    assert client.messages.requests[0]["tools"][0]["name"] == "weather"
    assert client.messages.requests[1]["messages"][-1]["content"][0]["type"] == "tool_result"
    assert run.usage.input_tokens == 4
    assert run.usage.output_tokens == 6


def test_claude_adapter_runs_scripted_user_turns_as_real_multi_turn() -> None:
    client = FakeClient([text_response("第一轮回答"), text_response("第二轮回答")])
    adapter = ClaudeAgentAdapter(AgentConfig(provider="anthropic"), client=client)
    case = EvalCase(id="multi_001", input="开始", scenario={"user_simulator": {"type": "scripted", "turns": ["继续"]}})

    run = asyncio.run(adapter.run(case, context=None))

    assert run.final_output == "第二轮回答"
    assert [message.role for message in run.messages] == ["user", "assistant", "user", "assistant"]
    assert [message.content for message in run.messages] == ["开始", "第一轮回答", "继续", "第二轮回答"]
    assert len(client.messages.requests) == 2
    assert client.messages.requests[1]["messages"] == [
        {"role": "user", "content": "开始"},
        {"role": "assistant", "content": "第一轮回答"},
        {"role": "user", "content": "继续"},
    ]
