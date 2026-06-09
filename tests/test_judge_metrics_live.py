import os

import pytest

from config import EvaluatorConfig
from evaluators.judge_metrics import JudgeMetricEvaluator
from schemas import AgentRun, EvalCase


@pytest.mark.anthropic_live
@pytest.mark.skipif(not os.environ.get("ANTHROPIC_API_KEY"), reason="ANTHROPIC_API_KEY is required for live Anthropic judge metric test")
def test_live_answer_relevancy_metric_returns_eval_result() -> None:
    case = EvalCase(id="live_relevancy", input="What is the refund deadline?", expected={})
    run = AgentRun(case_id="live_relevancy", final_output="Refund requests must be made within 30 days of purchase.")
    evaluator = JudgeMetricEvaluator(EvaluatorConfig(type="answer_relevancy", threshold=0.7, settings={"max_output_tokens": 1000}), "answer_relevancy")

    result = pytest.importorskip("asyncio").run(evaluator.evaluate(case, run))

    assert result.evaluator == "answer_relevancy"
    assert 0 <= result.score <= 1
    assert result.judgements
    assert "judge_usage" in result.metrics
