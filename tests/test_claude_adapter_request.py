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
        usage=SimpleNamespace(input_tokens=1, output_tokens=2, cache_creation_input_tokens=0, cache_read_input_tokens=0),
        model_dump=lambda mode="json": {"content": [{"type": "text", "text": text}]},
    )


def request_for(config: AgentConfig):
    client = FakeClient([text_response("ok")])
    adapter = ClaudeAgentAdapter(config, client=client)

    asyncio.run(adapter.run(EvalCase(id="c1", input="hello"), context=None))

    return client.messages.requests[0]


def test_claude_adapter_does_not_send_temperature_for_opus_4_models() -> None:
    request = request_for(AgentConfig(provider="anthropic", model="claude-opus-4-8", temperature=0.2))

    assert "temperature" not in request


def test_claude_adapter_sends_temperature_for_non_opus_model_when_configured() -> None:
    request = request_for(AgentConfig(provider="anthropic", model="claude-haiku-4-5", temperature=0.2))

    assert request["temperature"] == 0.2


def test_claude_adapter_forwards_thinking_and_output_config() -> None:
    thinking = {"type": "adaptive"}
    output_config = {"effort": "high"}

    request = request_for(AgentConfig(provider="anthropic", thinking=thinking, output_config=output_config))

    assert request["thinking"] == thinking
    assert request["output_config"] == output_config


def test_claude_adapter_applies_cached_system_prompt() -> None:
    request = request_for(
        AgentConfig(
            provider="anthropic",
            system="You are a helpful evaluator.",
            cache_system_prompt=True,
            cache_control={"type": "ephemeral"},
        )
    )

    assert request["system"] == [
        {
            "type": "text",
            "text": "You are a helpful evaluator.",
            "cache_control": {"type": "ephemeral"},
        }
    ]
    assert "cache_control" not in request


def test_claude_adapter_applies_top_level_cache_control_without_cached_system() -> None:
    request = request_for(AgentConfig(provider="anthropic", cache_control={"type": "ephemeral"}, cache_system_prompt=False))

    assert request["cache_control"] == {"type": "ephemeral"}
