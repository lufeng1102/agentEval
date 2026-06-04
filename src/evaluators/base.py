from __future__ import annotations

from typing import Protocol

from schemas import AgentRun, EvalCase, EvalResult


class Evaluator(Protocol):
    name: str

    async def evaluate(self, case: EvalCase, run: AgentRun) -> EvalResult:
        """Evaluate an agent run."""
