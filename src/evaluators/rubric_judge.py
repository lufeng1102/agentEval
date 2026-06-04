from __future__ import annotations

import json
from typing import Any

import anthropic

from config import EvaluatorConfig
from schemas import AgentRun, EvalCase, EvalResult, Usage


class RubricJudgeEvaluator:
    name = "rubric_judge"

    def __init__(self, config: EvaluatorConfig):
        self.config = config
        self.client = anthropic.AsyncAnthropic()

    async def evaluate(self, case: EvalCase, run: AgentRun) -> EvalResult:
        if not case.rubric:
            return EvalResult(
                case_id=case.id,
                evaluator=self.name,
                score=0,
                passed=False,
                failure_reason="case has no rubric",
            )

        prompt = _build_judge_prompt(case, run)
        try:
            response = await self.client.messages.create(
                model=self.config.judge_model,
                max_tokens=16000,
                thinking={"type": "adaptive"},
                output_config={"effort": "high"},
                cache_control={"type": "ephemeral"},
                system=[
                    {
                        "type": "text",
                        "text": "You are a strict evaluator. Return only JSON with keys score, passed, reasoning, evidence.",
                        "cache_control": {"type": "ephemeral"},
                    }
                ],
                messages=[{"role": "user", "content": prompt}],
            )
        except anthropic.APIError as exc:
            return EvalResult(
                case_id=case.id,
                evaluator=self.name,
                score=0,
                passed=False,
                failure_reason=f"judge API error: {exc}",
            )

        text = _extract_text(response.content)
        judgement = _parse_json(text)
        score = float(judgement.get("score", 0))
        passed = bool(judgement.get("passed", score >= self.config.threshold))
        return EvalResult(
            case_id=case.id,
            evaluator=self.name,
            score=max(0.0, min(1.0, score)),
            passed=passed,
            judgements=[judgement],
            metrics={"judge_usage": _usage_dict(response)},
            failure_reason=None if passed else judgement.get("reasoning", "rubric judge failed the case"),
        )


def _build_judge_prompt(case: EvalCase, run: AgentRun) -> str:
    return json.dumps(
        {
            "case_id": case.id,
            "input": case.input if isinstance(case.input, str) else [message.model_dump(mode="json") for message in case.input],
            "expected": case.expected,
            "rubric": case.rubric,
            "agent_output": run.final_output,
            "tool_calls": [tool.model_dump(mode="json") for tool in run.tool_calls],
            "instruction": "Score from 0 to 1. Pass only if the output satisfies the rubric. Return strict JSON only.",
        },
        ensure_ascii=False,
        sort_keys=True,
    )


def _extract_text(content: list[Any]) -> str:
    return "".join(getattr(block, "text", "") for block in content if getattr(block, "type", None) == "text").strip()


def _parse_json(text: str) -> dict[str, Any]:
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        start = text.find("{")
        end = text.rfind("}")
        if start >= 0 and end > start:
            try:
                return json.loads(text[start : end + 1])
            except json.JSONDecodeError:
                pass
    return {"score": 0, "passed": False, "reasoning": "judge returned non-JSON output", "evidence": text}


def _usage_dict(response: Any) -> dict[str, int]:
    usage = getattr(response, "usage", None)
    if usage is None:
        return Usage().model_dump()
    return Usage(
        input_tokens=getattr(usage, "input_tokens", 0) or 0,
        output_tokens=getattr(usage, "output_tokens", 0) or 0,
        cache_creation_input_tokens=getattr(usage, "cache_creation_input_tokens", 0) or 0,
        cache_read_input_tokens=getattr(usage, "cache_read_input_tokens", 0) or 0,
    ).model_dump()
