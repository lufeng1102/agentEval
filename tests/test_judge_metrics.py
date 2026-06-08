import pytest

from config import EvaluatorConfig
from evaluators import build_evaluator
from evaluators.judge_metrics import JUDGE_METRIC_TYPES, get_required_facts, get_retrieval_context, sanitize_metric_payload
from schemas import AgentRun, EvalCase


@pytest.mark.parametrize("metric", sorted(JUDGE_METRIC_TYPES))
def test_judge_metric_evaluator_returns_eval_result_from_case_mock(metric: str) -> None:
    case = EvalCase(
        id="c1",
        input="What is the refund deadline?",
        expected={
            "retrieval_context": ["Refunds are available within 30 days."],
            "required_facts": ["30 days"],
            "task": {"goal": "Answer refund deadline", "success_criteria": ["mention 30 days"]},
            "conversation": {"expected_behaviors": ["be helpful"]},
            "judge_metrics": {metric: {"score": 0.9, "passed": True, "reason": "ok", "metrics": {"metric": metric}}},
        },
    )
    run = AgentRun(case_id="c1", final_output="Refunds are available within 30 days.")
    evaluator = build_evaluator(EvaluatorConfig(type=metric, threshold=0.8))

    result = pytest.importorskip("asyncio").run(evaluator.evaluate(case, run))

    assert result.evaluator == metric
    assert result.score == 0.9
    assert result.passed is True
    assert result.failure_reason is None
    assert result.metrics["metric"] == metric


def test_judge_metric_threshold_failure_and_failure_type() -> None:
    case = EvalCase(id="c1", input="q", expected={"judge_metrics": {"answer_relevancy": {"score": 0.2, "reason": "off topic"}}})
    run = AgentRun(case_id="c1", final_output="unrelated")
    evaluator = build_evaluator(EvaluatorConfig(type="answer_relevancy", threshold=0.7))

    result = pytest.importorskip("asyncio").run(evaluator.evaluate(case, run))

    assert result.passed is False
    assert result.failure_type == "irrelevant_answer"
    assert result.failure_reason == "off topic"


def test_context_metric_missing_context_fails_clearly() -> None:
    case = EvalCase(id="c1", input="q", expected={"judge_metrics": {"faithfulness": {"score": 1, "passed": True}}})
    run = AgentRun(case_id="c1", final_output="answer")
    evaluator = build_evaluator(EvaluatorConfig(type="faithfulness"))

    result = pytest.importorskip("asyncio").run(evaluator.evaluate(case, run))

    assert result.passed is False
    assert result.failure_type == "missing_context"


def test_context_extraction_supports_expected_and_run_artifacts() -> None:
    case = EvalCase(id="c1", input="q", expected={"retrieval_context": ["expected ctx"], "required_facts": ["fact"]})
    run = AgentRun(case_id="c1", artifacts={"retrieval_context": ["artifact ctx"]})

    assert get_retrieval_context(case, run) == ["expected ctx"]
    assert get_retrieval_context(case, run, "run.artifacts.retrieval_context") == ["artifact ctx"]
    assert get_required_facts(case) == ["fact"]


def test_config_mock_judgement_used_when_case_mock_absent() -> None:
    case = EvalCase(id="c1", input="q", expected={})
    run = AgentRun(case_id="c1", final_output="answer")
    evaluator = build_evaluator(EvaluatorConfig(type="answer_relevancy", settings={"mock_judgement": {"score": 0.8, "passed": True, "reason": "config ok"}}))

    result = pytest.importorskip("asyncio").run(evaluator.evaluate(case, run))

    assert result.passed is True
    assert result.judgements[0]["reason"] == "config ok"


def test_metric_sanitizer_redacts_nested_secrets_and_truncates() -> None:
    payload = {"authorization": "Bearer secret", "nested": {"token": "abc"}, "text": "x" * 20}

    sanitized = sanitize_metric_payload(payload, max_chars=5)

    assert sanitized["authorization"] == "[REDACTED]"
    assert sanitized["nested"]["token"] == "[REDACTED]"
    assert sanitized["text"] == "xxxxx...[truncated]"
