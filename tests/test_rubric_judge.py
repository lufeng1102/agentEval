import asyncio
from types import SimpleNamespace

from config import EvaluatorConfig
from evaluators.rubric_judge import RubricJudgeEvaluator
from schemas import AgentRun, EvalCase


class FakeMessages:
    def __init__(self, responses):
        self.responses = list(responses)
        self.requests = []

    async def create(self, **request):
        self.requests.append(request)
        return self.responses.pop(0)


class FakeClient:
    def __init__(self, responses):
        self.messages = FakeMessages(responses)


def judge_response(text: str, usage=None):
    usage = usage or SimpleNamespace(input_tokens=3, output_tokens=4, cache_creation_input_tokens=5, cache_read_input_tokens=6)
    return SimpleNamespace(
        content=[SimpleNamespace(type="text", text=text)],
        usage=usage,
        model_dump=lambda mode="json": {"content": [{"type": "text", "text": text}]},
    )


def evaluator_with_response(text: str, config: EvaluatorConfig | None = None) -> RubricJudgeEvaluator:
    evaluator = RubricJudgeEvaluator(config or EvaluatorConfig(type="rubric_judge"))
    evaluator.client = FakeClient([judge_response(text)])
    return evaluator


def test_rubric_judge_requires_case_rubric() -> None:
    evaluator = RubricJudgeEvaluator(EvaluatorConfig(type="rubric_judge"))

    result = asyncio.run(evaluator.evaluate(EvalCase(id="c1", input="q"), AgentRun(case_id="c1")))

    assert not result.passed
    assert result.score == 0
    assert result.failure_reason == "case has no rubric"


def test_rubric_judge_parses_json_pass() -> None:
    evaluator = evaluator_with_response('{"score": 0.9, "passed": true, "reasoning": "good", "evidence": ["matched"]}')
    case = EvalCase(id="c1", input="q", rubric="Answer correctly")

    result = asyncio.run(evaluator.evaluate(case, AgentRun(case_id="c1", final_output="answer")))

    assert result.passed
    assert result.score == 0.9
    assert result.failure_reason is None
    assert result.judgements == [{"score": 0.9, "passed": True, "reasoning": "good", "evidence": ["matched"]}]
    assert result.metrics["judge_usage"]["input_tokens"] == 3
    assert result.metrics["judge_usage"]["output_tokens"] == 4


def test_rubric_judge_uses_threshold_when_passed_missing() -> None:
    passing = evaluator_with_response('{"score": 0.7, "reasoning": "enough"}', EvaluatorConfig(type="rubric_judge", threshold=0.7))
    failing = evaluator_with_response('{"score": 0.69, "reasoning": "not enough"}', EvaluatorConfig(type="rubric_judge", threshold=0.7))
    case = EvalCase(id="c1", input="q", rubric="Answer correctly")

    pass_result = asyncio.run(passing.evaluate(case, AgentRun(case_id="c1")))
    fail_result = asyncio.run(failing.evaluate(case, AgentRun(case_id="c1")))

    assert pass_result.passed
    assert not fail_result.passed
    assert fail_result.failure_reason == "not enough"


def test_rubric_judge_handles_non_json_response() -> None:
    evaluator = evaluator_with_response("not json")
    case = EvalCase(id="c1", input="q", rubric="Answer correctly")

    result = asyncio.run(evaluator.evaluate(case, AgentRun(case_id="c1")))

    assert not result.passed
    assert result.score == 0
    assert result.judgements[0]["reasoning"] == "judge returned non-JSON output"
    assert result.failure_reason == "judge returned non-JSON output"
