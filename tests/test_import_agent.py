from pathlib import Path

from typer.testing import CliRunner

from cli import _build_imported_agent, app
from config import AgentConfig, AppConfig


runner = CliRunner()


def test_cli_runs_imported_agent_adapter(tmp_path: Path) -> None:
    dataset = tmp_path / "dataset.yaml"
    dataset.write_text(
        """
cases:
  - id: c1
    input: q
    expected:
      required_facts: [factory]
    evaluators: [contains]
""".strip(),
        encoding="utf-8",
    )
    config = tmp_path / "config.yaml"
    config.write_text(
        """
agent:
  provider: import
  static_response: factory ok
  settings:
    import_path: tests.imported_agent.build_agent
evaluators:
  - type: contains
report:
  formats: [json]
""".strip(),
        encoding="utf-8",
    )

    result = runner.invoke(app, ["run", "--dataset", str(dataset), "--config", str(config), "--out", str(tmp_path / "run")])

    assert result.exit_code == 0, result.output
    assert "pass_rate=100.00%" in result.output


def test_build_imported_agent_requires_import_path() -> None:
    try:
        _build_imported_agent(AppConfig(agent=AgentConfig(provider="import")))
    except Exception as exc:
        assert "import agent requires agent.settings.import_path" in str(exc)
    else:
        raise AssertionError("expected missing import path failure")


def test_build_imported_agent_rejects_malformed_import_path() -> None:
    try:
        _build_imported_agent(AppConfig(agent=AgentConfig(provider="import", settings={"import_path": "missingattr"})))
    except Exception as exc:
        assert "invalid agent import path" in str(exc)
    else:
        raise AssertionError("expected malformed import path failure")


def test_build_imported_agent_supports_factory_without_config() -> None:
    agent = _build_imported_agent(AppConfig(agent=AgentConfig(provider="import", settings={"import_path": "tests.imported_agent.build_agent_without_config"})))

    assert agent.response == "no config ok"


def test_build_imported_agent_type_error_falls_back_to_no_config_call() -> None:
    try:
        _build_imported_agent(AppConfig(agent=AgentConfig(provider="import", settings={"import_path": "tests.imported_agent.build_agent_type_error"})))
    except TypeError as exc:
        assert "missing 1 required positional argument" in str(exc)
    else:
        raise AssertionError("expected fallback TypeError from no-config call")


def test_cli_imported_agent_reports_missing_module(tmp_path: Path) -> None:
    config = tmp_path / "config.yaml"
    config.write_text(
        """
agent:
  provider: import
  settings:
    import_path: missing_module.build_agent
evaluators:
  - type: contains
""".strip(),
        encoding="utf-8",
    )

    result = runner.invoke(app, ["run", "--dataset", "examples/datasets/basic_agent_eval.yaml", "--config", str(config), "--out", str(tmp_path / "run"), "--case", "factual_001"])

    assert result.exit_code != 0
    assert isinstance(result.exception, ModuleNotFoundError)
    assert "missing_module" in str(result.exception)
