import asyncio
from pathlib import Path

import pytest

from config import AppConfig, EvaluatorConfig, RunnerConfig
from runners import EvalExecutor
from runners.trace import JsonlTraceWriter, read_jsonl
from schemas import AgentRun, EvalCase, EvalResult, RunContext


class CountingAgent:
    def __init__(self) -> None:
        self.calls = 0

    async def run(self, case: EvalCase, context: RunContext) -> AgentRun:
        self.calls += 1
        return AgentRun(case_id=case.id, final_output="fresh")


class PassEvaluator:
    name = "contains"

    async def evaluate(self, case: EvalCase, run: AgentRun) -> EvalResult:
        return EvalResult(case_id=case.id, evaluator=self.name, score=1, passed=True)


def test_read_jsonl_returns_empty_for_missing_file(tmp_path: Path) -> None:
    assert read_jsonl(tmp_path / "missing.jsonl") == []


def test_read_jsonl_returns_empty_for_empty_file(tmp_path: Path) -> None:
    path = tmp_path / "empty.jsonl"
    path.write_text("", encoding="utf-8")

    assert read_jsonl(path) == []


def test_read_jsonl_raises_for_invalid_json_line(tmp_path: Path) -> None:
    path = tmp_path / "bad.jsonl"
    path.write_text('{"ok": true}\n{bad json}\n', encoding="utf-8")

    with pytest.raises(ValueError):
        read_jsonl(path)


def test_jsonl_trace_writer_creates_parent_directories(tmp_path: Path) -> None:
    path = tmp_path / "nested" / "traces.jsonl"

    JsonlTraceWriter(path).write([AgentRun(case_id="c1", final_output="ok")])

    assert read_jsonl(path)[0]["case_id"] == "c1"


def test_executor_resume_uses_last_duplicate_trace_for_same_case_repeat(tmp_path: Path) -> None:
    traces = tmp_path / "traces.jsonl"
    writer = JsonlTraceWriter(traces)
    writer.write(
        [
            AgentRun(case_id="c1", repeat_index=0, final_output="old"),
            AgentRun(case_id="c1", repeat_index=0, final_output="newer"),
        ]
    )
    case = EvalCase(id="c1", input="q")
    config = AppConfig(runner=RunnerConfig(repeats=1), evaluators=[EvaluatorConfig(type="contains")])
    agent = CountingAgent()
    executor = EvalExecutor(agent, [PassEvaluator()], config)

    runs, _ = asyncio.run(executor.run([case], tmp_path, resume=True))

    assert agent.calls == 0
    assert runs[0].final_output == "newer"
    assert executor.resumed_runs == 1
