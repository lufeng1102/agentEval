from __future__ import annotations

import asyncio
from collections.abc import Sequence
from pathlib import Path

from agents.base import AgentAdapter
from config import AppConfig
from evaluators.base import Evaluator
from environments import EnvironmentSessionRecord, environment_enabled, prepare_environment
from runners.trace import JsonlTraceWriter, read_jsonl
from schemas import AgentRun, EvalCase, EvalResult, RunContext


class EvalExecutor:
    def __init__(self, agent: AgentAdapter, evaluators: Sequence[Evaluator], config: AppConfig):
        self.agent = agent
        self.evaluators = list(evaluators)
        self.config = config
        self.resumed_runs = 0

    async def run(self, cases: Sequence[EvalCase], output_dir: str | Path, resume: bool = False) -> tuple[list[AgentRun], list[EvalResult]]:
        output_path = Path(output_dir)
        output_path.mkdir(parents=True, exist_ok=True)
        context = RunContext(output_dir=output_path, config=self.config.model_dump(mode="json"))
        semaphore = asyncio.Semaphore(max(1, self.config.runner.concurrency))
        repeats = max(1, self.config.runner.repeats)
        jobs = [(case, repeat_index) for case in cases for repeat_index in range(repeats)]
        existing = _load_existing_runs(output_path) if resume else {}
        self.resumed_runs = len(existing)

        async def run_one(case: EvalCase, repeat_index: int) -> tuple[AgentRun, EnvironmentSessionRecord | None]:
            key = (case.id, repeat_index)
            if key in existing:
                return existing[key], None
            async with semaphore:
                timeout = case.timeout_seconds or self.config.runner.timeout_seconds
                prepared_env = prepare_environment(case, repeat_index, output_path, self.config.environment) if environment_enabled(self.config.environment, case) else None
                trial_context = context
                if prepared_env is not None:
                    await prepared_env.run_commands("setup", prepared_env.setup_commands)
                    prepared_env.snapshot_before()
                    trial_context = RunContext(
                        output_dir=output_path,
                        config=self.config.model_dump(mode="json"),
                        environment={
                            "type": prepared_env.record.type,
                            "root": prepared_env.record.root,
                            "fixture": prepared_env.record.fixture,
                            "case_id": case.id,
                            "repeat_index": repeat_index,
                        },
                    )
                for attempt in range(self.config.runner.retries + 1):
                    try:
                        run = await asyncio.wait_for(self.agent.run(case, trial_context), timeout=timeout)
                        run.repeat_index = repeat_index
                        if prepared_env is not None:
                            await prepared_env.run_commands("test", prepared_env.test_commands)
                        run = await _finalize_environment(run, prepared_env)
                        return run, prepared_env.record if prepared_env else None
                    except Exception as exc:  # keep the whole suite running
                        if attempt >= self.config.runner.retries:
                            run = AgentRun(case_id=case.id, repeat_index=repeat_index, errors=[f"{exc.__class__.__name__}: {exc}"])
                            run = await _finalize_environment(run, prepared_env)
                            return run, prepared_env.record if prepared_env else None
                run = AgentRun(case_id=case.id, repeat_index=repeat_index, errors=["unreachable retry state"])
                run = await _finalize_environment(run, prepared_env)
                return run, prepared_env.record if prepared_env else None

        run_outputs = await asyncio.gather(*(run_one(case, repeat_index) for case, repeat_index in jobs))
        runs = [run for run, _ in run_outputs]
        environment_records = [record for _, record in run_outputs if record is not None]
        JsonlTraceWriter(output_path / "traces.jsonl").write(runs)
        if environment_records:
            JsonlTraceWriter(output_path / "environment.jsonl").write(environment_records)

        results: list[EvalResult] = []
        for (case, _), run in zip(jobs, runs, strict=True):
            selected = set(case.evaluators or [])
            for evaluator in self.evaluators:
                if selected and evaluator.name not in selected:
                    continue
                result = await evaluator.evaluate(case, run)
                result.repeat_index = run.repeat_index
                results.append(result)

        JsonlTraceWriter(output_path / "results.jsonl").write(results)
        return runs, results


async def _finalize_environment(run: AgentRun, prepared_env) -> AgentRun:
    if prepared_env is None:
        return run
    prepared_env.snapshot_after()
    prepared_env.compute_diff()
    await prepared_env.run_commands("teardown", prepared_env.teardown_commands)
    run.artifacts["environment"] = prepared_env.artifact_summary()
    return run


def _load_existing_runs(output_path: Path) -> dict[tuple[str, int], AgentRun]:
    existing: dict[tuple[str, int], AgentRun] = {}
    for item in read_jsonl(output_path / "traces.jsonl"):
        run = AgentRun.model_validate(item)
        existing[(run.case_id, run.repeat_index)] = run
    return existing
