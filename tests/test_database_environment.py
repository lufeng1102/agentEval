import asyncio
import sqlite3
from pathlib import Path

from config import EnvironmentConfig
from environments.database import prepare_database_environment
from evaluators.environment import EnvironmentEvaluator
from schemas import AgentRun, EvalCase


def _sqlite_fixture(path: Path) -> Path:
    with sqlite3.connect(path) as connection:
        connection.execute("create table users (id integer primary key, name text)")
        connection.execute("insert into users (name) values ('alice')")
    return path


def test_database_environment_copies_fixture_and_records_queries(tmp_path: Path) -> None:
    fixture = _sqlite_fixture(tmp_path / "fixture.sqlite")
    prepared = prepare_database_environment(
        EvalCase(id="db1", input="check"),
        0,
        tmp_path / "run",
        EnvironmentConfig(type="database", fixture=fixture, test_queries=["select * from users where name = 'alice'"]),
    )

    asyncio.run(prepared.run_commands("test", prepared.test_commands))

    assert prepared.database_path != fixture
    assert prepared.record.database[0].row_count == 1
    assert prepared.record.database[0].rows[0]["name"] == "alice"


def test_database_environment_records_query_errors(tmp_path: Path) -> None:
    prepared = prepare_database_environment(
        EvalCase(id="db1", input="check"),
        0,
        tmp_path / "run",
        EnvironmentConfig(type="database", test_queries=["select * from missing"]),
    )

    asyncio.run(prepared.run_commands("test", prepared.test_commands))

    assert prepared.record.database[0].error


def test_environment_evaluator_checks_database_rows() -> None:
    query = "select * from users where name = 'alice'"
    case = EvalCase(id="db1", input="check", expected={"environment": {"database": {"required_rows": [{"query": query, "min_count": 1}], "max_query_failures": 0}}})
    run = AgentRun(case_id="db1", artifacts={"environment": {"type": "database", "database": [{"phase": "test", "query": query, "row_count": 1, "rows": [{"name": "alice"}], "error": None}]}})

    result = asyncio.run(EnvironmentEvaluator().evaluate(case, run))

    assert result.passed is True
    assert result.metrics["queries"] == 1


def test_environment_evaluator_fails_forbidden_database_rows() -> None:
    query = "select * from users where name = 'mallory'"
    case = EvalCase(id="db1", input="check", expected={"environment": {"database": {"forbidden_rows": [{"query": query}]}}})
    run = AgentRun(case_id="db1", artifacts={"environment": {"type": "database", "database": [{"phase": "test", "query": query, "row_count": 1, "rows": [{"name": "mallory"}], "error": None}]}})

    result = asyncio.run(EnvironmentEvaluator().evaluate(case, run))

    assert result.passed is False
    assert "forbidden rows" in result.failure_reason
