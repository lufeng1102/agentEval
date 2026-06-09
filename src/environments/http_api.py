from __future__ import annotations

import json
import shutil
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urljoin

from config import EnvironmentConfig
from environments.filesystem import _merged_environment, _run_command
from environments.models import EnvironmentSessionRecord, HttpCheckResult
from schemas import EvalCase


@dataclass
class PreparedHttpApiEnvironment:
    record: EnvironmentSessionRecord
    base_url: str
    setup_commands: list[str]
    test_commands: list[str]
    teardown_commands: list[str]
    setup_checks: list[dict[str, Any]]
    test_checks: list[dict[str, Any]]
    teardown_checks: list[dict[str, Any]]
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
        for command in commands if commands is not None else []:
            self.record.commands.append(await _run_command(self.root, phase, command, self.command_timeout_seconds, self.max_command_output_chars))
        await self.run_checks(phase, _checks_for_phase(self, phase))

    async def run_checks(self, phase: str, checks: list[dict[str, Any]] | None = None) -> None:
        for check in checks or []:
            self.record.http.append(_run_check(self.base_url, phase, check, self.max_command_output_chars))

    def artifact_summary(self) -> dict[str, Any]:
        command_failures = [command for command in self.record.commands if command.timed_out or (command.exit_code is not None and command.exit_code != 0) or command.exit_code is None]
        http_failures = [check for check in self.record.http if check.error or check.status_code is None]
        return {
            "type": self.record.type,
            "root": self.record.root,
            "base_url": self.base_url,
            "case_id": self.record.case_id,
            "repeat_index": self.record.repeat_index,
            "commands": [command.model_dump(mode="json") for command in self.record.commands],
            "database": [query.model_dump(mode="json") for query in self.record.database],
            "http": [check.model_dump(mode="json") for check in self.record.http],
            "summary": {
                "commands": len(self.record.commands),
                "command_failures": len(command_failures),
                "queries": len(self.record.database),
                "query_failures": sum(1 for query in self.record.database if query.error),
                "http_checks": len(self.record.http),
                "http_failures": len(http_failures),
            },
        }


def prepare_http_api_environment(case: EvalCase, repeat_index: int, output_dir: str | Path, config: EnvironmentConfig) -> PreparedHttpApiEnvironment:
    merged = _merged_environment(config, case)
    session_dir = Path(output_dir) / "envs" / _safe_id(case.id) / str(repeat_index)
    if session_dir.exists():
        shutil.rmtree(session_dir)
    session_dir.mkdir(parents=True, exist_ok=True)
    return PreparedHttpApiEnvironment(
        record=EnvironmentSessionRecord(case_id=case.id, repeat_index=repeat_index, type="http_api", root=str(session_dir)),
        base_url=str(merged.get("base_url") or ""),
        setup_commands=[str(item) for item in merged.get("setup_commands", [])],
        test_commands=[str(item) for item in merged.get("test_commands", [])],
        teardown_commands=[str(item) for item in merged.get("teardown_commands", [])],
        setup_checks=[dict(item) for item in merged.get("setup_checks", []) or []],
        test_checks=[dict(item) for item in merged.get("test_checks", []) or []],
        teardown_checks=[dict(item) for item in merged.get("teardown_checks", []) or []],
        command_timeout_seconds=float(merged.get("command_timeout_seconds", 120)),
        max_command_output_chars=int(merged.get("max_command_output_chars", 20000)),
    )


def _checks_for_phase(prepared: PreparedHttpApiEnvironment, phase: str) -> list[dict[str, Any]]:
    if phase == "setup":
        return prepared.setup_checks
    if phase == "test":
        return prepared.test_checks
    if phase == "teardown":
        return prepared.teardown_checks
    return []


def _run_check(base_url: str, phase: str, spec: dict[str, Any], max_chars: int) -> HttpCheckResult:
    method = str(spec.get("method") or "GET").upper()
    url = str(spec.get("url") or urljoin(base_url.rstrip("/") + "/", str(spec.get("path") or "").lstrip("/")))
    body = spec.get("body")
    if "json" in spec:
        body = json.dumps(spec.get("json"), ensure_ascii=False).encode("utf-8")
    elif isinstance(body, str):
        body = body.encode("utf-8")
    headers = {str(k): str(v) for k, v in (spec.get("headers") or {}).items()}
    if "json" in spec:
        headers.setdefault("Content-Type", "application/json")
    started = time.perf_counter()
    status_code = None
    response_text = ""
    parsed_json = None
    error = None
    try:
        request = urllib.request.Request(url, data=body, headers=headers, method=method)
        with urllib.request.urlopen(request, timeout=float(spec.get("timeout_seconds") or 30)) as response:
            status_code = response.status
            response_text = response.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as exc:
        status_code = exc.code
        response_text = exc.read().decode("utf-8", errors="replace")
    except Exception as exc:  # keep suite running; evaluator decides pass/fail
        error = f"{exc.__class__.__name__}: {exc}"
    if response_text:
        try:
            parsed_json = json.loads(response_text)
        except json.JSONDecodeError:
            parsed_json = None
    expected_status = spec.get("expected_status")
    if expected_status is not None and status_code != int(expected_status):
        error = error or f"expected status {expected_status}, got {status_code}"
    return HttpCheckResult(phase=phase, method=method, url=url, status_code=status_code, response_body=_truncate(response_text, max_chars), json_body=parsed_json, error=error, duration_ms=int((time.perf_counter() - started) * 1000))


def _truncate(value: str, max_chars: int) -> str:
    if max_chars < 0 or len(value) <= max_chars:
        return value
    return value[:max_chars] + "\n...[truncated]"


def _safe_id(case_id: str) -> str:
    safe = "".join(char if char.isalnum() or char in {"-", "_", "."} else "_" for char in case_id)
    return safe or "case"
