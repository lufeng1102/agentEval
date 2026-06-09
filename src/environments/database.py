from __future__ import annotations

import shutil
import sqlite3
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from config import EnvironmentConfig
from environments.filesystem import _merged_environment, _run_command
from environments.models import DatabaseQueryResult, EnvironmentSessionRecord
from schemas import EvalCase


@dataclass
class PreparedDatabaseEnvironment:
    record: EnvironmentSessionRecord
    database_path: Path
    setup_commands: list[str]
    test_commands: list[str]
    teardown_commands: list[str]
    setup_queries: list[Any]
    test_queries: list[Any]
    teardown_queries: list[Any]
    command_timeout_seconds: float
    max_command_output_chars: int

    @property
    def root(self) -> Path:
        return Path(self.record.root)

    def snapshot_before(self) -> None:
        return None

    def snapshot_after(self) -> None:
        return None

    def compute_diff(self) -> None:
        return None

    async def run_commands(self, phase: str, commands: list[str] | None = None) -> None:
        await self.run_queries(phase, _queries_for_phase(self, phase))
        for command in commands if commands is not None else []:
            self.record.commands.append(await _run_command(self.root, phase, command, self.command_timeout_seconds, self.max_command_output_chars))

    async def run_queries(self, phase: str, queries: list[Any] | None = None) -> None:
        for query in queries or []:
            self.record.database.append(_run_query(self.database_path, phase, query))

    def artifact_summary(self) -> dict[str, Any]:
        query_failures = [query for query in self.record.database if query.error]
        command_failures = [command for command in self.record.commands if command.timed_out or (command.exit_code is not None and command.exit_code != 0) or command.exit_code is None]
        return {
            "type": self.record.type,
            "fixture": self.record.fixture,
            "root": self.record.root,
            "database_path": str(self.database_path),
            "case_id": self.record.case_id,
            "repeat_index": self.record.repeat_index,
            "commands": [command.model_dump(mode="json") for command in self.record.commands],
            "database": [query.model_dump(mode="json") for query in self.record.database],
            "http": [check.model_dump(mode="json") for check in self.record.http],
            "summary": {
                "commands": len(self.record.commands),
                "command_failures": len(command_failures),
                "queries": len(self.record.database),
                "query_failures": len(query_failures),
                "http_checks": len(self.record.http),
                "http_failures": sum(1 for check in self.record.http if check.error or check.status_code is None),
            },
        }


def prepare_database_environment(case: EvalCase, repeat_index: int, output_dir: str | Path, config: EnvironmentConfig) -> PreparedDatabaseEnvironment:
    merged = _merged_environment(config, case)
    fixture = merged.get("fixture")
    database_name = str(merged.get("database_path") or "database.sqlite")
    session_dir = Path(output_dir) / "envs" / _safe_id(case.id) / str(repeat_index)
    if session_dir.exists():
        shutil.rmtree(session_dir)
    session_dir.mkdir(parents=True, exist_ok=True)
    database_path = session_dir / database_name
    database_path.parent.mkdir(parents=True, exist_ok=True)
    if fixture:
        shutil.copy2(Path(fixture), database_path)
    else:
        sqlite3.connect(database_path).close()
    return PreparedDatabaseEnvironment(
        record=EnvironmentSessionRecord(case_id=case.id, repeat_index=repeat_index, type="database", fixture=str(fixture) if fixture else None, root=str(session_dir)),
        database_path=database_path,
        setup_commands=[str(item) for item in merged.get("setup_commands", [])],
        test_commands=[str(item) for item in merged.get("test_commands", [])],
        teardown_commands=[str(item) for item in merged.get("teardown_commands", [])],
        setup_queries=list(merged.get("setup_queries", []) or []),
        test_queries=list(merged.get("test_queries", []) or []),
        teardown_queries=list(merged.get("teardown_queries", []) or []),
        command_timeout_seconds=float(merged.get("command_timeout_seconds", 120)),
        max_command_output_chars=int(merged.get("max_command_output_chars", 20000)),
    )


def _queries_for_phase(prepared: PreparedDatabaseEnvironment, phase: str) -> list[Any]:
    if phase == "setup":
        return prepared.setup_queries
    if phase == "test":
        return prepared.test_queries
    if phase == "teardown":
        return prepared.teardown_queries
    return []


def _run_query(database_path: Path, phase: str, spec: Any) -> DatabaseQueryResult:
    query, params = _query_and_params(spec)
    started = time.perf_counter()
    rows: list[dict[str, Any]] = []
    error = None
    try:
        with sqlite3.connect(database_path) as connection:
            connection.row_factory = sqlite3.Row
            cursor = connection.execute(query, params)
            if cursor.description:
                rows = [dict(row) for row in cursor.fetchall()]
            connection.commit()
    except Exception as exc:  # keep suite running; evaluator decides pass/fail
        error = f"{exc.__class__.__name__}: {exc}"
    return DatabaseQueryResult(phase=phase, query=query, params=list(params), rows=rows, row_count=len(rows), error=error, duration_ms=int((time.perf_counter() - started) * 1000))


def _query_and_params(spec: Any) -> tuple[str, list[Any]]:
    if isinstance(spec, str):
        return spec, []
    if isinstance(spec, dict):
        return str(spec.get("query", "")), list(spec.get("params") or [])
    return str(spec), []


def _safe_id(case_id: str) -> str:
    safe = "".join(char if char.isalnum() or char in {"-", "_", "."} else "_" for char in case_id)
    return safe or "case"
