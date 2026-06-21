from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path

from config import AppConfig
from evaluators.base import Evaluator
from runners.trace import JsonlTraceWriter
from schemas import AgentRun, EvalCase, EvalResult


class ReplayExecutor:
    def __init__(self, evaluators: Sequence[Evaluator], config: AppConfig):
        self.evaluators = list(evaluators)
        self.config = config

    async def run(self, cases: Sequence[EvalCase], runs: Sequence[AgentRun], output_dir: str | Path) -> tuple[list[AgentRun], list[EvalResult]]:
        output_path = Path(output_dir)
        output_path.mkdir(parents=True, exist_ok=True)
        cases_by_id = {case.id: case for case in cases}
        replay_runs = list(runs)
        missing = [run.case_id for run in replay_runs if run.case_id not in cases_by_id]
        if missing:
            raise ValueError(f"replay traces missing cases: {missing}")

        JsonlTraceWriter(output_path / "traces.jsonl").write(replay_runs)
        results: list[EvalResult] = []
        for run in replay_runs:
            case = cases_by_id[run.case_id]
            selected = set(case.evaluators or [])
            for evaluator in self.evaluators:
                if selected and evaluator.name not in selected:
                    continue
                result = await evaluator.evaluate(case, run)
                result.repeat_index = run.repeat_index
                results.append(result)
        JsonlTraceWriter(output_path / "results.jsonl").write(results)
        return replay_runs, results
