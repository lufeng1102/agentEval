import pytest
from pydantic import ValidationError

from config import AgentConfig, AppConfig, ReportConfig, RunnerConfig
from schemas import ChatMessage, EvalDataset, EvalResult, ToolCall


def test_runner_config_currently_allows_non_positive_values() -> None:
    config = RunnerConfig(concurrency=0, repeats=0, timeout_seconds=-1)

    assert config.concurrency == 0
    assert config.repeats == 0
    assert config.timeout_seconds == -1


def test_agent_config_currently_allows_non_positive_max_tokens() -> None:
    config = AgentConfig(max_tokens=0)

    assert config.max_tokens == 0


def test_report_config_currently_allows_unknown_formats() -> None:
    config = ReportConfig(formats=["json", "bad"])

    assert config.formats == ["json", "bad"]


def test_chat_message_rejects_unknown_role() -> None:
    with pytest.raises(ValidationError):
        ChatMessage(role="invalid", content="hello")


def test_tool_call_rejects_non_dict_input() -> None:
    with pytest.raises(ValidationError):
        ToolCall(name="lookup", input="not a dict")


def test_eval_result_rejects_score_outside_unit_interval() -> None:
    with pytest.raises(ValidationError):
        EvalResult(case_id="c1", evaluator="contains", score=1.1, passed=True)

    with pytest.raises(ValidationError):
        EvalResult(case_id="c1", evaluator="contains", score=-0.1, passed=False)


def test_eval_dataset_currently_allows_empty_cases() -> None:
    dataset = EvalDataset(cases=[])

    assert dataset.cases == []


def test_app_config_accepts_unknown_report_format_snapshot() -> None:
    config = AppConfig(report=ReportConfig(formats=["unknown"]))

    assert config.report.formats == ["unknown"]
