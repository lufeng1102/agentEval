from __future__ import annotations

import asyncio
import subprocess
import time
from pathlib import Path
from typing import Any, Callable

from adapters.contract import adapter_metadata
from config import AgentConfig
from schemas import AgentRun, ChatMessage, EvalCase, RunContext


class ClaudeCodeAgentAdapter:
    """Adapter that evaluates a prompt through the Claude Code CLI."""

    def __init__(self, config: AgentConfig, runner: Callable[..., subprocess.CompletedProcess] | None = None):
        self.config = config
        self.runner = runner or subprocess.run

    async def run(self, case: EvalCase, context: RunContext) -> AgentRun:
        return await asyncio.to_thread(self.run_sync, case, context)

    def run_sync(self, case: EvalCase, context: RunContext | None) -> AgentRun:
        started = time.perf_counter()
        prompt = self._prompt(case)
        command = self._command(prompt)
        cwd = str(self._cwd(context))
        timeout = self.config.settings.get("timeout_seconds")
        completed = self.runner(command, cwd=cwd, capture_output=True, text=True, timeout=timeout)
        output = (completed.stdout or "").strip()
        errors = []
        if completed.returncode != 0:
            errors.append((completed.stderr or f"Claude Code exited with {completed.returncode}").strip())
        return AgentRun(
            case_id=case.id,
            messages=[ChatMessage(role="user", content=case.input if isinstance(case.input, str) else str(case.input))],
            final_output=output,
            latency_ms=(time.perf_counter() - started) * 1000,
            errors=errors,
            raw_response={"command": command, "stdout": completed.stdout, "stderr": completed.stderr, "returncode": completed.returncode},
            artifacts={
                "adapter": adapter_metadata(
                    "claude_code",
                    framework="claude_code_cli",
                    capabilities={"messages": True},
                    lossiness=["Claude Code CLI does not expose structured tool calls, spans, or token usage in --print mode."],
                ),
                "claude_code": {"command": command, "cwd": cwd, "returncode": completed.returncode},
            },
        )

    def _command(self, prompt: str) -> list[str]:
        executable = str(self.config.settings.get("executable", "claude"))
        args = [executable, "--print"]
        extra_args = self.config.settings.get("args") or []
        args.extend(str(item) for item in extra_args)
        args.append(prompt)
        return args

    def _prompt(self, case: EvalCase) -> str:
        user_input = case.input if isinstance(case.input, str) else "\n".join(str(message.content) for message in case.input)
        agent_name = self.config.settings.get("agent_name")
        if agent_name:
            return f"Use the {agent_name} agent to answer this evaluation case.\n\n{user_input}"
        return str(user_input)

    def _cwd(self, context: RunContext | None) -> Path:
        configured = self.config.settings.get("cwd")
        if configured:
            return Path(str(configured))
        if context is not None:
            return context.output_dir.parent
        return Path.cwd()
