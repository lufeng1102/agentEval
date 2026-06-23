from __future__ import annotations

import json
from pathlib import Path

import pytest

from instrumentation import AgentEvalTracer, record_usage, span, tool_call, trace_agent_run
from schemas import AgentTrace


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


def _read_traces(path: Path) -> list[AgentTrace]:
    return [AgentTrace.model_validate(json.loads(line)) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def test_sync_decorator_writes_trace_and_preserves_return_value(tmp_path: Path) -> None:
    path = tmp_path / "traces.jsonl"

    @trace_agent_run(trace_path=path, case_id="c1", agent_id="agent")
    def run_agent() -> str:
        return "answer"

    assert run_agent() == "answer"
    traces = _read_traces(path)
    assert len(traces) == 1
    assert traces[0].case_id == "c1"
    assert traces[0].agent_id == "agent"
    assert traces[0].final_output == "answer"
    assert traces[0].metadata["instrumentation"]["schema_version"] == "agenteval.trace.v1"


@pytest.mark.anyio
async def test_async_decorator_records_usage_span_and_tool_call(tmp_path: Path, anyio_backend: str) -> None:
    assert anyio_backend == "asyncio"
    path = tmp_path / "traces.jsonl"

    @trace_agent_run(trace_path=path, case_id="c1")
    async def run_agent() -> str:
        record_usage(input_tokens=2, output_tokens=3)
        async with span("llm.generate", kind="llm", input={"prompt": "hi"}) as sp:
            sp.set_output({"text": "hello"})
        async with tool_call("search", input={"query": "hi"}) as call:
            call.set_output({"hits": 1})
        return "hello"

    assert await run_agent() == "hello"
    trace = _read_traces(path)[0]
    assert trace.usage.input_tokens == 2
    assert trace.usage.output_tokens == 3
    assert [item.name for item in trace.spans] == ["llm.generate", "search"]
    assert trace.tool_calls[0].name == "search"
    assert trace.tool_calls[0].output == {"hits": 1}


def test_context_manager_records_nested_spans_and_messages(tmp_path: Path) -> None:
    path = tmp_path / "traces.jsonl"

    with AgentEvalTracer(path, case_id="c1") as trace:
        trace.add_message("user", "question")
        with trace.span("parent", kind="chain"):
            with trace.span("child", kind="tool"):
                pass
        trace.add_message("assistant", "answer")
        trace.set_final_output("answer")

    output = _read_traces(path)[0]
    assert output.messages[0].content == "question"
    assert output.messages[1].content == "answer"
    parent, child = output.spans
    assert child.parent_span_id == parent.span_id


def test_user_exception_is_preserved_and_recorded(tmp_path: Path) -> None:
    path = tmp_path / "traces.jsonl"

    @trace_agent_run(trace_path=path, case_id="c1")
    def run_agent() -> str:
        raise ValueError("boom")

    with pytest.raises(ValueError, match="boom"):
        run_agent()

    trace = _read_traces(path)[0]
    assert trace.errors == ["boom"]


def test_fail_open_ignores_writer_errors() -> None:
    class BrokenWriter:
        def append(self, trace: AgentTrace) -> None:
            raise OSError("disk full")

    with AgentEvalTracer("unused.jsonl", writer=BrokenWriter()):
        pass


def test_fail_closed_raises_writer_errors() -> None:
    class BrokenWriter:
        def append(self, trace: AgentTrace) -> None:
            raise OSError("disk full")

    with pytest.raises(OSError, match="disk full"):
        with AgentEvalTracer("unused.jsonl", writer=BrokenWriter(), fail_open=False):
            pass


def test_redacts_sensitive_values(tmp_path: Path) -> None:
    path = tmp_path / "traces.jsonl"

    with AgentEvalTracer(path, case_id="c1") as trace:
        with trace.tool_call("login", input={"password": "secret", "nested": {"token": "abc"}}) as call:
            call.set_output({"authorization": "Bearer abc", "ok": True})

    output = _read_traces(path)[0]
    assert output.tool_calls[0].input["password"] == "[REDACTED]"
    assert output.tool_calls[0].input["nested"]["token"] == "[REDACTED]"
    assert output.tool_calls[0].output["authorization"] == "[REDACTED]"
