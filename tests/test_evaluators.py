import asyncio

from evaluators.exact_match import ContainsEvaluator, ExactMatchEvaluator
from evaluators.safety import SafetyEvaluator
from evaluators.trajectory import TrajectoryEvaluator
from schemas import AgentRun, EvalCase, ToolCall


def test_contains_evaluator_scores_required_facts() -> None:
    case = EvalCase(id="c1", input="question", expected={"required_facts": ["H2O", "水"]})
    run = AgentRun(case_id="c1", final_output="水的化学式是 H2O。")

    result = asyncio.run(ContainsEvaluator().evaluate(case, run))

    assert result.passed
    assert result.score == 1


def test_exact_match_evaluator_fails_different_output() -> None:
    case = EvalCase(id="c1", input="question", expected={"answer": "H2O"})
    run = AgentRun(case_id="c1", final_output="水的化学式是 H2O。")

    result = asyncio.run(ExactMatchEvaluator().evaluate(case, run))

    assert not result.passed


def test_trajectory_evaluator_checks_required_tools() -> None:
    case = EvalCase(id="c1", input="question", expected={"required_tools": ["weather"]})
    run = AgentRun(case_id="c1", tool_calls=[ToolCall(name="weather", input={"city": "北京"})])

    result = asyncio.run(TrajectoryEvaluator().evaluate(case, run))

    assert result.passed


def test_trajectory_evaluator_fails_for_forbidden_tools() -> None:
    case = EvalCase(id="c1", input="question", expected={"forbidden_tools": ["delete_user"]})
    run = AgentRun(case_id="c1", tool_calls=[ToolCall(name="delete_user")])

    result = asyncio.run(TrajectoryEvaluator().evaluate(case, run))

    assert not result.passed
    assert result.metrics["forbidden_called"] == ["delete_user"]


def test_trajectory_evaluator_fails_for_max_tool_calls() -> None:
    case = EvalCase(id="c1", input="question", expected={"max_tool_calls": 1})
    run = AgentRun(case_id="c1", tool_calls=[ToolCall(name="a"), ToolCall(name="b")])

    result = asyncio.run(TrajectoryEvaluator().evaluate(case, run))

    assert not result.passed
    assert "tool call count" in result.failure_reason


def test_trajectory_evaluator_fails_for_max_latency() -> None:
    case = EvalCase(id="c1", input="question", expected={"max_latency_ms": 100})
    run = AgentRun(case_id="c1", latency_ms=250)

    result = asyncio.run(TrajectoryEvaluator().evaluate(case, run))

    assert not result.passed
    assert "latency" in result.failure_reason


def test_trajectory_evaluator_strict_reference_with_arguments_passes() -> None:
    case = EvalCase(
        id="c1",
        input="question",
        expected={
            "reference_trajectory": [
                {"name": "weather", "input": {"city": "北京"}},
                {"name": "summarize", "input": {"style": "advice"}},
            ],
            "trajectory": {"match_mode": "strict", "check_arguments": True},
        },
    )
    run = AgentRun(
        case_id="c1",
        tool_calls=[
            ToolCall(name="weather", input={"city": "北京", "unit": "c"}),
            ToolCall(name="summarize", input={"style": "advice"}),
        ],
    )

    result = asyncio.run(TrajectoryEvaluator().evaluate(case, run))

    assert result.passed


def test_trajectory_evaluator_strict_reference_fails_on_order() -> None:
    case = EvalCase(
        id="c1",
        input="question",
        expected={
            "reference_trajectory": [{"name": "weather"}, {"name": "summarize"}],
            "trajectory": {"match_mode": "strict"},
        },
    )
    run = AgentRun(case_id="c1", tool_calls=[ToolCall(name="summarize"), ToolCall(name="weather")])

    result = asyncio.run(TrajectoryEvaluator().evaluate(case, run))

    assert not result.passed


def test_trajectory_evaluator_unordered_reference_passes() -> None:
    case = EvalCase(
        id="c1",
        input="question",
        expected={
            "reference_trajectory": [{"name": "weather"}, {"name": "summarize"}],
            "trajectory": {"match_mode": "unordered"},
        },
    )
    run = AgentRun(case_id="c1", tool_calls=[ToolCall(name="summarize"), ToolCall(name="weather")])

    result = asyncio.run(TrajectoryEvaluator().evaluate(case, run))

    assert result.passed


def test_trajectory_evaluator_subset_reference_passes_with_extra_tool() -> None:
    case = EvalCase(
        id="c1",
        input="question",
        expected={
            "reference_trajectory": [{"name": "weather"}],
            "trajectory": {"match_mode": "subset"},
        },
    )
    run = AgentRun(case_id="c1", tool_calls=[ToolCall(name="weather"), ToolCall(name="summarize")])

    result = asyncio.run(TrajectoryEvaluator().evaluate(case, run))

    assert result.passed


def test_trajectory_evaluator_argument_contains_fails() -> None:
    case = EvalCase(
        id="c1",
        input="question",
        expected={
            "reference_trajectory": [{"name": "weather", "input": {"city": "北京"}}],
            "trajectory": {"match_mode": "subset", "check_arguments": True},
        },
    )
    run = AgentRun(case_id="c1", tool_calls=[ToolCall(name="weather", input={"city": "上海"})])

    result = asyncio.run(TrajectoryEvaluator().evaluate(case, run))

    assert not result.passed
    assert result.metrics["argument_mismatches"]


def test_trajectory_evaluator_milestones_pass() -> None:
    case = EvalCase(
        id="c1",
        input="question",
        expected={"milestones": [{"id": "m1", "required_tool": "weather"}, {"id": "m2", "required_output": "出行建议"}]},
    )
    run = AgentRun(case_id="c1", final_output="这里是出行建议", tool_calls=[ToolCall(name="weather")])

    result = asyncio.run(TrajectoryEvaluator().evaluate(case, run))

    assert result.passed


def test_trajectory_evaluator_milestone_dependencies_block_progress() -> None:
    case = EvalCase(
        id="c1",
        input="question",
        expected={
            "milestones": [
                {"id": "lookup", "required_tool": "lookup"},
                {"id": "cancel", "depends_on": ["lookup"], "required_tool": "cancel"},
            ]
        },
    )
    run = AgentRun(case_id="c1", tool_calls=[ToolCall(name="cancel")])

    result = asyncio.run(TrajectoryEvaluator().evaluate(case, run))

    assert not result.passed
    assert result.failure_type == "milestone_not_reached"
    assert result.metrics["progress_rate"] == 0


def test_safety_evaluator_requires_refusal() -> None:
    case = EvalCase(id="c1", input="bad", expected={"should_refuse": True, "forbidden_terms": ["密码爆破步骤"]})
    run = AgentRun(case_id="c1", final_output="抱歉，我不能帮助入侵邮箱。可以提供账号安全建议。")

    result = asyncio.run(SafetyEvaluator().evaluate(case, run))

    assert result.passed
