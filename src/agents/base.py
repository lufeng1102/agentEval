from __future__ import annotations

from typing import Protocol

from schemas import AgentRun, EvalCase, RunContext


class AgentAdapter(Protocol):
    async def run(self, case: EvalCase, context: RunContext) -> AgentRun:
        """Run an evaluation case and return a complete trace."""
