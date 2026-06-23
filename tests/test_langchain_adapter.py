from __future__ import annotations

import asyncio
from pathlib import Path

from typer.testing import CliRunner

from adapters.conformance import validate_agent_run_contract
from agents.langchain_adapter import LangChainAgentAdapter
from cli import _build_agent, app
from config import AgentConfig, AppConfig
from schemas import EvalCase, RunContext


def test_langchain_adapter_invokes_runnable_and_maps_steps(tmp_path: Path) -> None:
    adapter = LangChainAgentAdapter(AgentConfig(provider="langchain", settings={"import_path": "tests.fake_langchain_app.build_runnable"}))

    run = asyncio.run(adapter.run(EvalCase(id="c1", input="q"), RunContext(output_dir=tmp_path)))

    assert run.final_output == "langchain answer: q"
    assert run.tool_calls[0].name == "search"
    assert run.spans[0].name == "langchain.invoke"
    assert run.spans[1].kind == "tool"
    assert run.artifacts["adapter"]["adapter_name"] == "langchain"
    assert [issue for issue in validate_agent_run_contract(run) if issue.severity == "error"] == []


def test_langchain_adapter_supports_async_runnable_and_spans(tmp_path: Path) -> None:
    adapter = LangChainAgentAdapter(AgentConfig(provider="langchain", settings={"import_path": "tests.fake_langchain_app.build_async_runnable"}))

    run = asyncio.run(adapter.run(EvalCase(id="c1", input="q"), RunContext(output_dir=tmp_path)))

    assert run.final_output == "async answer"
    assert [span.kind for span in run.spans] == ["chain", "retrieval"]
    assert run.artifacts["adapter"]["capabilities"]["retrieval"] is True


def test_langchain_adapter_supports_callable_and_custom_keys(tmp_path: Path) -> None:
    adapter = LangChainAgentAdapter(AgentConfig(provider="langchain", settings={"import_path": "tests.fake_langchain_app.build_callable", "input_key": "question", "output_key": "content"}))

    run = asyncio.run(adapter.run(EvalCase(id="c1", input="q"), RunContext(output_dir=tmp_path)))

    assert run.final_output == "callable: q"
    assert run.tool_calls[0].name == "lookup"


def test_langchain_adapter_records_errors(tmp_path: Path) -> None:
    adapter = LangChainAgentAdapter(AgentConfig(provider="langchain", settings={"import_path": "tests.fake_langchain_app.build_failing"}))

    run = asyncio.run(adapter.run(EvalCase(id="c1", input="q"), RunContext(output_dir=tmp_path)))

    assert run.final_output == ""
    assert run.errors == ["langchain boom"]
    assert [issue for issue in validate_agent_run_contract(run) if issue.severity == "error"] == []


def test_build_agent_supports_langchain_provider() -> None:
    agent = _build_agent(AppConfig(agent=AgentConfig(provider="langchain", settings={"import_path": "tests.fake_langchain_app.build_runnable"})))

    assert isinstance(agent, LangChainAgentAdapter)


def test_cli_runs_langchain_provider(tmp_path: Path) -> None:
    dataset = tmp_path / "dataset.yaml"
    dataset.write_text(
        """
cases:
  - id: c1
    input: q
    expected:
      required_facts: [langchain answer]
    evaluators: [contains]
""".strip(),
        encoding="utf-8",
    )
    config = tmp_path / "config.yaml"
    config.write_text(
        """
agent:
  provider: langchain
  settings:
    import_path: tests.fake_langchain_app.build_runnable
evaluators:
  - type: contains
report:
  formats: [json]
""".strip(),
        encoding="utf-8",
    )

    result = CliRunner().invoke(app, ["run", "--dataset", str(dataset), "--config", str(config), "--out", str(tmp_path / "run")])

    assert result.exit_code == 0, result.output
    assert "pass_rate=100.00%" in result.output
