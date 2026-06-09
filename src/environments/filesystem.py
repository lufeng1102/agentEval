from __future__ import annotations

import asyncio
import fnmatch
import hashlib
import shutil
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from config import EnvironmentConfig
from environments.models import CommandResult, EnvironmentDiff, EnvironmentSessionRecord, EnvironmentSnapshot, FileSnapshot
from schemas import EvalCase


@dataclass
class PreparedEnvironment:
    record: EnvironmentSessionRecord
    include_patterns: list[str]
    exclude_patterns: list[str]
    protected_paths: list[str]
    setup_commands: list[str]
    test_commands: list[str]
    teardown_commands: list[str]
    command_timeout_seconds: float
    max_command_output_chars: int

    @property
    def root(self) -> Path:
        return Path(self.record.root)

    def snapshot_before(self) -> None:
        self.record.before = snapshot_directory(self.root, self.include_patterns, self.exclude_patterns)

    def snapshot_after(self) -> None:
        self.record.after = snapshot_directory(self.root, self.include_patterns, self.exclude_patterns)

    def compute_diff(self) -> None:
        if self.record.before is None or self.record.after is None:
            self.record.diff = EnvironmentDiff()
            return
        self.record.diff = diff_snapshots(self.record.before, self.record.after, self.protected_paths)

    async def run_commands(self, phase: str, commands: list[str] | None = None) -> None:
        for command in commands if commands is not None else []:
            self.record.commands.append(await _run_command(self.root, phase, command, self.command_timeout_seconds, self.max_command_output_chars))

    def artifact_summary(self) -> dict[str, Any]:
        diff = self.record.diff or EnvironmentDiff()
        after = self.record.after or EnvironmentSnapshot(root_hash="", files={})
        command_failures = [command for command in self.record.commands if command.timed_out or (command.exit_code is not None and command.exit_code != 0) or command.exit_code is None]
        return {
            "type": self.record.type,
            "fixture": self.record.fixture,
            "root": self.record.root,
            "case_id": self.record.case_id,
            "repeat_index": self.record.repeat_index,
            "after": after.model_dump(mode="json"),
            "diff": diff.model_dump(mode="json"),
            "commands": [command.model_dump(mode="json") for command in self.record.commands],
            "database": [query.model_dump(mode="json") for query in self.record.database],
            "http": [check.model_dump(mode="json") for check in self.record.http],
            "summary": {
                "created_files": len(diff.created),
                "modified_files": len(diff.modified),
                "deleted_files": len(diff.deleted),
                "protected_path_violations": len(diff.protected_path_violations),
                "commands": len(self.record.commands),
                "command_failures": len(command_failures),
                "queries": len(self.record.database),
                "query_failures": sum(1 for query in self.record.database if query.error),
                "http_checks": len(self.record.http),
                "http_failures": sum(1 for check in self.record.http if check.error or check.status_code is None),
            },
        }


def environment_enabled(config: EnvironmentConfig, case: EvalCase | None = None) -> bool:
    return _merged_environment(config, case).get("type", "none") != "none"


def prepare_filesystem_environment(case: EvalCase, repeat_index: int, output_dir: str | Path, config: EnvironmentConfig) -> PreparedEnvironment:
    merged = _merged_environment(config, case)
    env_type = str(merged.get("type", "none"))
    if env_type != "filesystem":
        raise ValueError(f"unsupported environment type for P0: {env_type}")
    if str(merged.get("isolation", "copy")) != "copy":
        raise ValueError("filesystem environment only supports isolation=copy")
    fixture = merged.get("fixture")
    if fixture is None:
        raise ValueError("filesystem environment requires fixture")
    fixture_path = Path(fixture)
    if not fixture_path.exists() or not fixture_path.is_dir():
        raise ValueError(f"environment fixture must be an existing directory: {fixture}")

    session_dir = Path(output_dir) / "envs" / _safe_id(case.id) / str(repeat_index)
    workspace = session_dir / "workspace"
    if session_dir.exists():
        shutil.rmtree(session_dir)
    session_dir.mkdir(parents=True, exist_ok=True)
    shutil.copytree(fixture_path, workspace)

    prepared = PreparedEnvironment(
        record=EnvironmentSessionRecord(case_id=case.id, repeat_index=repeat_index, type=env_type, fixture=str(fixture_path), root=str(workspace)),
        include_patterns=[str(item) for item in merged.get("include_patterns", ["**/*"])],
        exclude_patterns=[str(item) for item in merged.get("exclude_patterns", [])],
        protected_paths=[str(item) for item in merged.get("protected_paths", [])],
        setup_commands=[str(item) for item in merged.get("setup_commands", [])],
        test_commands=[str(item) for item in merged.get("test_commands", [])],
        teardown_commands=[str(item) for item in merged.get("teardown_commands", [])],
        command_timeout_seconds=float(merged.get("command_timeout_seconds", 120)),
        max_command_output_chars=int(merged.get("max_command_output_chars", 20000)),
    )
    prepared.snapshot_before()
    return prepared


def snapshot_directory(root: str | Path, include_patterns: list[str], exclude_patterns: list[str]) -> EnvironmentSnapshot:
    root_path = Path(root)
    files: dict[str, FileSnapshot] = {}
    for path in sorted(item for item in root_path.rglob("*") if item.is_file()):
        rel = path.relative_to(root_path).as_posix()
        if not _included(rel, include_patterns, exclude_patterns):
            continue
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        files[rel] = FileSnapshot(path=rel, sha256=digest, size_bytes=path.stat().st_size)
    root_hash = _root_hash(files)
    return EnvironmentSnapshot(root_hash=root_hash, files=files)


def diff_snapshots(before: EnvironmentSnapshot, after: EnvironmentSnapshot, protected_paths: list[str]) -> EnvironmentDiff:
    before_paths = set(before.files)
    after_paths = set(after.files)
    created = sorted(after_paths - before_paths)
    deleted = sorted(before_paths - after_paths)
    modified = sorted(path for path in before_paths & after_paths if before.files[path].sha256 != after.files[path].sha256)
    touched = created + modified + deleted
    protected = sorted(path for path in touched if _matches_any(path, protected_paths))
    return EnvironmentDiff(created=created, modified=modified, deleted=deleted, protected_path_violations=protected)


async def _run_command(root: Path, phase: str, command: str, timeout_seconds: float, max_output_chars: int) -> CommandResult:
    started = time.perf_counter()
    process = await asyncio.create_subprocess_shell(command, cwd=str(root), stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
    timed_out = False
    try:
        stdout_bytes, stderr_bytes = await asyncio.wait_for(process.communicate(), timeout=timeout_seconds)
    except TimeoutError:
        timed_out = True
        process.kill()
        stdout_bytes, stderr_bytes = await process.communicate()
    duration_ms = int((time.perf_counter() - started) * 1000)
    return CommandResult(
        phase=phase,
        command=command,
        exit_code=process.returncode,
        stdout=_truncate(stdout_bytes.decode("utf-8", errors="replace"), max_output_chars),
        stderr=_truncate(stderr_bytes.decode("utf-8", errors="replace"), max_output_chars),
        duration_ms=duration_ms,
        timed_out=timed_out,
    )


def _truncate(value: str, max_chars: int) -> str:
    if max_chars < 0 or len(value) <= max_chars:
        return value
    return value[:max_chars] + "\n...[truncated]"


def _merged_environment(config: EnvironmentConfig, case: EvalCase | None) -> dict[str, Any]:
    merged = config.model_dump(mode="python")
    if case is not None:
        merged.update(case.environment or {})
    return merged


def _included(path: str, include_patterns: list[str], exclude_patterns: list[str]) -> bool:
    includes = include_patterns or ["**/*"]
    return _matches_any(path, includes) and not _matches_any(path, exclude_patterns)


def _matches_any(path: str, patterns: list[str]) -> bool:
    return any(fnmatch.fnmatch(path, pattern) or fnmatch.fnmatch(path, pattern.rstrip("/**")) for pattern in patterns)


def _root_hash(files: dict[str, FileSnapshot]) -> str:
    hasher = hashlib.sha256()
    for path in sorted(files):
        hasher.update(path.encode("utf-8"))
        hasher.update(files[path].sha256.encode("utf-8"))
    return hasher.hexdigest()


def _safe_id(case_id: str) -> str:
    safe = "".join(char if char.isalnum() or char in {"-", "_", "."} else "_" for char in case_id)
    return safe or "case"
