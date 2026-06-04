from __future__ import annotations

import json
from typing import Any

from config import EvaluatorConfig
from schemas import AgentRun, EvalCase, EvalResult


class TrajectoryJudgeEvaluator:
    name = "trajectory_judge"

    def __init__(self, config: EvaluatorConfig | None = None):
        self.config = config or EvaluatorConfig(type="trajectory_judge")

    async def evaluate(self, case: EvalCase, run: AgentRun) -> EvalResult:
        mock = self.config.settings.get("mock_judgement") or case.expected.get("trajectory_judgement")
        if mock is not None:
            judgement = dict(mock)
        else:
            judgement = await self._judge_with_anthropic(case, run)

        score = float(judgement.get("score", 0))
        passed = bool(judgement.get("passed", score >= self.config.threshold))
        return EvalResult(
            case_id=case.id,
            evaluator=self.name,
            score=max(0.0, min(1.0, score)),
            passed=passed,
            judgements=[judgement],
            metrics={"tool_calls": [call.model_dump(mode="json") for call in run.tool_calls]},
            failure_reason=None if passed else judgement.get("reasoning", "trajectory judge failed the case"),
            failure_type=None if passed else "trajectory_judge_failure",
        )

    async def _judge_with_anthropic(self, case: EvalCase, run: AgentRun) -> dict[str, Any]:
        try:
            import anthropic
        except ModuleNotFoundError:
            return {"score": 0, "passed": False, "reasoning": "anthropic package is not installed", "evidence": []}

        client = anthropic.AsyncAnthropic()
        prompt = json.dumps(
            {
                "case_id": case.id,
                "input": case.input if isinstance(case.input, str) else [message.model_dump(mode="json") for message in case.input],
                "expected": case.expected,
                "tool_calls": [call.model_dump(mode="json") for call in run.tool_calls],
                "final_output": run.final_output,
                "instruction": "Evaluate whether the agent trajectory is appropriate. Return JSON with score, passed, reasoning, evidence.",
            },
            ensure_ascii=False,
            sort_keys=True,
        )
        try:
            response = await client.messages.create(
                model=self.config.judge_model,
                max_tokens=16000,
                thinking={"type": "adaptive"},
                output_config={"effort": "high"},
                cache_control={"type": "ephemeral"},
                system="You are a strict trajectory evaluator. Return only JSON.",
                messages=[{"role": "user", "content": prompt}],
            )
        except anthropic.APIError as exc:
            return {"score": 0, "passed": False, "reasoning": f"judge API error: {exc}", "evidence": []}
        text = "".join(getattr(block, "text", "") for block in response.content if getattr(block, "type", None) == "text")
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            return {"score": 0, "passed": False, "reasoning": "judge returned non-JSON output", "evidence": text}
