import asyncio
import sys
from pathlib import Path

from config import EnvironmentConfig
from environments.filesystem import prepare_filesystem_environment
from schemas import EvalCase


def _fixture(path: Path) -> Path:
    (path / "src").mkdir(parents=True)
    (path / "src" / "auth.py").write_text("ok", encoding="utf-8")
    return path


def test_environment_command_success_and_failure_are_recorded(tmp_path: Path) -> None:
    prepared = prepare_filesystem_environment(EvalCase(id="c1", input="x"), 0, tmp_path / "run", EnvironmentConfig(type="filesystem", fixture=_fixture(tmp_path / "fixture")))

    asyncio.run(prepared.run_commands("test", [f"{sys.executable} -c \"print('ok')\"", f"{sys.executable} -c \"import sys; sys.exit(3)\""]))

    assert len(prepared.record.commands) == 2
    assert prepared.record.commands[0].exit_code == 0
    assert prepared.record.commands[0].stdout.strip() == "ok"
    assert prepared.record.commands[1].exit_code == 3


def test_environment_command_timeout_is_recorded(tmp_path: Path) -> None:
    prepared = prepare_filesystem_environment(
        EvalCase(id="c1", input="x"),
        0,
        tmp_path / "run",
        EnvironmentConfig(type="filesystem", fixture=_fixture(tmp_path / "fixture"), command_timeout_seconds=0.01),
    )

    asyncio.run(prepared.run_commands("test", [f"{sys.executable} -c \"import time; time.sleep(1)\""]))

    assert prepared.record.commands[0].timed_out is True


def test_environment_command_output_is_truncated(tmp_path: Path) -> None:
    prepared = prepare_filesystem_environment(
        EvalCase(id="c1", input="x"),
        0,
        tmp_path / "run",
        EnvironmentConfig(type="filesystem", fixture=_fixture(tmp_path / "fixture"), max_command_output_chars=5),
    )

    asyncio.run(prepared.run_commands("test", [f"{sys.executable} -c \"print('abcdefghijklmnop')\""]))

    assert prepared.record.commands[0].stdout.startswith("abcde")
    assert "truncated" in prepared.record.commands[0].stdout
