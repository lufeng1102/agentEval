import asyncio
from types import SimpleNamespace

import pytest

from agents.claude_adapter import ClaudeAgentAdapter
from config import AgentConfig
from schemas import EvalCase


class FakeMessages:
    def __init__(self, responses):
        self.responses = list(responses)
        self.requests = []

    async def create(self, **request):
        self.requests.append(request)
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response


class FakeClient:
    def __init__(self, responses):
        self.messages = FakeMessages(responses)


def text_response(*texts: str, usage=None):
    return SimpleNamespace(
        content=[SimpleNamespace(type="text", text=text) for text in texts],
        usage=usage,
        model_dump=lambda mode="json": {"content": [{"type": "text", "text": text} for text in texts]},
    )


def tool_response(*blocks, usage=None):
    content = [SimpleNamespace(type="tool_use", id=tool_id, name=name, input=tool_input) for tool_id, name, tool_input in blocks]
    return SimpleNamespace(
        content=content,
        usage=usage,
        model_dump=lambda mode="json": {"content": [{"type": "tool_use", "id": item.id, "name": item.name, "input": item.input} for item in content]},
    )


def test_claude_adapter_defaults_missing_usage_to_zero() -> None:
    client = FakeClient([text_response("ok", usage=None)])
    adapter = ClaudeAgentAdapter(AgentConfig(provider="anthropic"), client=client)

    run = asyncio.run(adapter.run(EvalCase(id="c1", input="q"), context=None))

    assert run.final_output == "ok"
    assert run.usage.input_tokens == 0
    assert run.usage.output_tokens == 0


def test_claude_adapter_concatenates_multiple_text_blocks() -> None:
    client = FakeClient([text_response("hello ", "world")])
    adapter = ClaudeAgentAdapter(AgentConfig(provider="anthropic"), client=client)

    run = asyncio.run(adapter.run(EvalCase(id="c1", input="q"), context=None))

    assert run.final_output == "hello world"
    assert run.messages[-1].content == "hello world"


def test_claude_adapter_handles_multiple_tool_use_blocks_in_one_turn() -> None:
    client = FakeClient([
        tool_response(("toolu_1", "weather", {"city": "北京"}), ("toolu_2", "lookup", {"id": "A100"})),
        text_response("done"),
    ])
    adapter = ClaudeAgentAdapter(AgentConfig(provider="anthropic"), client=client)
    case = EvalCase(
        id="c1",
        input="q",
        scenario={
            "tools": [
                {"name": "weather", "input_schema": {"type": "object"}, "mock_output": {"condition": "sunny"}},
                {"name": "lookup", "input_schema": {"type": "object"}, "mock_output": {"status": "paid"}},
            ]
        },
    )

    run = asyncio.run(adapter.run(case, context=None))

    assert [call.name for call in run.tool_calls] == ["weather", "lookup"]
    tool_results = client.messages.requests[1]["messages"][-1]["content"]
    assert [result["tool_use_id"] for result in tool_results] == ["toolu_1", "toolu_2"]


def test_claude_adapter_marks_tool_result_errors() -> None:
    client = FakeClient([tool_response(("toolu_1", "weather", {})), text_response("done")])
    adapter = ClaudeAgentAdapter(AgentConfig(provider="anthropic"), client=client)
    case = EvalCase(
        id="c1",
        input="q",
        scenario={"tools": [{"name": "weather", "input_schema": {"type": "object", "required": ["city"], "properties": {"city": {"type": "string"}}}, "mock_output": {"condition": "sunny"}}]},
    )

    run = asyncio.run(adapter.run(case, context=None))

    assert run.tool_calls[0].error
    tool_result = client.messages.requests[1]["messages"][-1]["content"][0]
    assert tool_result["is_error"] is True
    assert tool_result["content"] == run.tool_calls[0].error


def test_claude_adapter_raises_when_tool_loop_exceeds_limit() -> None:
    client = FakeClient([tool_response(("toolu_1", "weather", {"city": "北京"}), usage=None)])
    adapter = ClaudeAgentAdapter(AgentConfig(provider="anthropic", settings={"max_tool_iterations": 0}), client=client)
    case = EvalCase(id="c1", input="q", scenario={"tools": [{"name": "weather", "input_schema": {"type": "object"}, "mock_output": {"condition": "sunny"}}]})

    with pytest.raises(RuntimeError, match="tool loop exceeded max_tool_iterations=0"):
        asyncio.run(adapter.run(case, context=None))
