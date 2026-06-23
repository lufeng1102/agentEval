from __future__ import annotations

import asyncio
from pathlib import Path
from types import SimpleNamespace

from adapters.conformance import validate_agent_run_contract
from agents.claude_adapter import ClaudeAgentAdapter
from agents.claude_code_adapter import ClaudeCodeAgentAdapter
from agents.langchain_adapter import LangChainAgentAdapter
from agents.static_adapter import StaticAgentAdapter
from config import AgentConfig
from schemas import AgentRun, EvalCase, RunContext, ToolCall, TraceSpan


def test_conformance_accepts_minimal_valid_run_with_adapter_metadata() -> None:
    run = AgentRun(
        case_id="case-1",
        final_output="ok",
        artifacts={
            "adapter": {
                "contract_version": "agenteval.adapter.v1",
                "adapter_name": "fake",
                "adapter_version": "0.1.0",
                "framework": "fake_framework",
                "capabilities": {"messages": True},
            }
        },
    )

    issues = validate_agent_run_contract(run)

    assert [item for item in issues if item.severity == "error"] == []


def test_conformance_warns_when_adapter_metadata_is_missing() -> None:
    run = AgentRun(case_id="case-1", final_output="ok")

    issues = validate_agent_run_contract(run)

    assert any(item.severity == "warning" and item.path == "artifacts.adapter" for item in issues)
    assert [item for item in issues if item.severity == "error"] == []


def test_conformance_strict_mode_requires_adapter_metadata() -> None:
    run = AgentRun(case_id="case-1", final_output="ok")

    issues = validate_agent_run_contract(run, require_adapter_metadata=True)

    assert any(item.severity == "error" and item.path == "artifacts.adapter" for item in issues)


def test_conformance_reports_tool_span_and_raw_response_errors() -> None:
    run = AgentRun(
        case_id="case-1",
        final_output="ok",
        raw_response={"bad": object()},
        tool_calls=[ToolCall(name="", input={"query": "x"}, output=object())],
        spans=[TraceSpan(span_id="child", name="custom", kind="unknown", parent_span_id="missing")],
        artifacts={
            "adapter": {
                "contract_version": "wrong",
                "adapter_name": "fake",
                "adapter_version": "0.1.0",
                "framework": "fake_framework",
                "capabilities": {},
            }
        },
    )

    issues = validate_agent_run_contract(run)

    paths = {item.path for item in issues}
    assert "tool_calls[0].name" in paths
    assert "tool_calls[0].output" in paths
    assert "spans[0].kind" in paths
    assert "raw_response" in paths
    assert "spans[0].parent_span_id" in paths
    assert "artifacts.adapter.contract_version" in paths


def test_conformance_reports_malformed_adapter_metadata() -> None:
    run = AgentRun(
        case_id="case-1",
        final_output="ok",
        artifacts={
            "adapter": {
                "contract_version": "agenteval.adapter.v1",
                "adapter_name": "",
                "adapter_version": "",
                "framework": "",
                "capabilities": {"messages": "yes"},
                "lossiness": [object()],
            }
        },
    )

    issues = validate_agent_run_contract(run, require_adapter_metadata=True)

    paths = {item.path for item in issues if item.severity == "error"}
    assert "artifacts.adapter.adapter_name" in paths
    assert "artifacts.adapter.adapter_version" in paths
    assert "artifacts.adapter.framework" in paths
    assert "artifacts.adapter.capabilities.messages" in paths
    assert "artifacts.adapter.lossiness" in paths


def test_builtin_adapters_emit_strict_conformant_runs(tmp_path: Path) -> None:
    runs = [
        asyncio.run(_static_run(tmp_path)),
        asyncio.run(_anthropic_run(tmp_path)),
        _claude_code_run(tmp_path),
        asyncio.run(_langchain_run(tmp_path)),
    ]

    for run in runs:
        issues = validate_agent_run_contract(run, require_adapter_metadata=True)
        assert [item for item in issues if item.severity == "error"] == []
        assert not any(item.path.startswith("artifacts.adapter") for item in issues)


def test_anthropic_request_sanitizes_current_model_parameters() -> None:
    adapter = ClaudeAgentAdapter(
        AgentConfig(
            provider="anthropic",
            model="claude-opus-4-8",
            temperature=0.2,
            thinking={"type": "enabled", "budget_tokens": 4096, "display": "summarized"},
        ),
        client=_FakeClient([_text_response("ok")]),
    )

    request = adapter._build_request([{"role": "user", "content": "hello"}], [])

    assert "temperature" not in request
    assert request["thinking"] == {"type": "adaptive", "display": "summarized"}


def test_anthropic_request_omits_invalid_fable_thinking() -> None:
    adapter = ClaudeAgentAdapter(
        AgentConfig(provider="anthropic", model="claude-fable-5", temperature=0.2, thinking={"type": "disabled"}),
        client=_FakeClient([_text_response("ok")]),
    )

    request = adapter._build_request([{"role": "user", "content": "hello"}], [])

    assert "temperature" not in request
    assert "thinking" not in request


def test_anthropic_refusal_is_returned_as_contract_error(tmp_path: Path) -> None:
    adapter = ClaudeAgentAdapter(AgentConfig(provider="anthropic"), client=_FakeClient([_refusal_response()]))

    run = asyncio.run(adapter.run(EvalCase(id="refusal", input="hello"), RunContext(output_dir=tmp_path / "refusal")))

    assert run.errors
    assert "refusal" in run.errors[0]
    issues = validate_agent_run_contract(run, require_adapter_metadata=True)
    assert [item for item in issues if item.severity == "error"] == []


async def _static_run(tmp_path: Path) -> AgentRun:
    adapter = StaticAgentAdapter("ok", tool_calls=[ToolCall(name="lookup", input={"q": "x"})])
    return await adapter.run(EvalCase(id="static", input="hello"), RunContext(output_dir=tmp_path / "static"))


async def _anthropic_run(tmp_path: Path) -> AgentRun:
    adapter = ClaudeAgentAdapter(AgentConfig(provider="anthropic"), client=_FakeClient([_text_response("ok")]))
    return await adapter.run(EvalCase(id="anthropic", input="hello"), RunContext(output_dir=tmp_path / "anthropic"))


def _claude_code_run(tmp_path: Path) -> AgentRun:
    adapter = ClaudeCodeAgentAdapter(AgentConfig(provider="claude_code", settings={"cwd": str(tmp_path)}), runner=_fake_runner)
    return adapter.run_sync(EvalCase(id="claude_code", input="hello"), RunContext(output_dir=tmp_path / "claude_code"))


async def _langchain_run(tmp_path: Path) -> AgentRun:
    adapter = LangChainAgentAdapter(AgentConfig(provider="langchain", settings={"import_path": "tests.fake_langchain_app.build_runnable"}))
    return await adapter.run(EvalCase(id="langchain", input="hello"), RunContext(output_dir=tmp_path / "langchain"))


class _FakeMessages:
    def __init__(self, responses):
        self.responses = list(responses)

    async def create(self, **request):
        return self.responses.pop(0)


class _FakeClient:
    def __init__(self, responses):
        self.messages = _FakeMessages(responses)


def _text_response(text: str):
    return SimpleNamespace(
        content=[SimpleNamespace(type="text", text=text)],
        usage=SimpleNamespace(input_tokens=1, output_tokens=2, cache_creation_input_tokens=0, cache_read_input_tokens=0),
        model_dump=lambda mode="json": {"content": [{"type": "text", "text": text}], "stop_reason": "end_turn"},
        stop_reason="end_turn",
    )


def _refusal_response():
    return SimpleNamespace(
        content=[],
        usage=SimpleNamespace(input_tokens=0, output_tokens=0, cache_creation_input_tokens=0, cache_read_input_tokens=0),
        stop_reason="refusal",
        stop_details=SimpleNamespace(category="cyber", explanation="declined"),
        model_dump=lambda mode="json": {"content": [], "stop_reason": "refusal", "stop_details": {"category": "cyber", "explanation": "declined"}},
    )


def _fake_runner(command, **kwargs):
    return SimpleNamespace(stdout="ok", stderr="", returncode=0)
