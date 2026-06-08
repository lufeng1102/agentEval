from __future__ import annotations

import importlib

from config import EvaluatorConfig
from evaluators.base import Evaluator
from evaluators.cost import CostEvaluator
from evaluators.exact_match import ContainsEvaluator, ExactMatchEvaluator
from evaluators.json_schema import JsonSchemaEvaluator
from evaluators.minefield import MinefieldEvaluator
from evaluators.regex import RegexEvaluator
from evaluators.safety import SafetyEvaluator
from evaluators.state import StateEvaluator
from evaluators.tool_output import ToolOutputEvaluator
from evaluators.trajectory import TrajectoryEvaluator
from evaluators.trajectory_judge import TrajectoryJudgeEvaluator
from evaluators.judge_metrics import JUDGE_METRIC_TYPES, JudgeMetricEvaluator


def build_evaluator(config: EvaluatorConfig) -> Evaluator:
    if config.type == "contains":
        return ContainsEvaluator()
    if config.type == "exact_match":
        return ExactMatchEvaluator()
    if config.type == "trajectory":
        return TrajectoryEvaluator()
    if config.type == "safety":
        return SafetyEvaluator()
    if config.type == "json_schema":
        return JsonSchemaEvaluator()
    if config.type == "regex":
        return RegexEvaluator()
    if config.type == "tool_output":
        return ToolOutputEvaluator()
    if config.type == "cost":
        return CostEvaluator(config)
    if config.type == "minefield":
        return MinefieldEvaluator()
    if config.type == "state":
        return StateEvaluator()
    if config.type == "trajectory_judge":
        return TrajectoryJudgeEvaluator(config)
    if config.type in JUDGE_METRIC_TYPES:
        return JudgeMetricEvaluator(config, config.type)
    if config.type in {"import", "plugin"}:
        return _build_imported_evaluator(config)
    if config.type == "rubric_judge":
        from evaluators.rubric_judge import RubricJudgeEvaluator

        return RubricJudgeEvaluator(config)
    raise ValueError(f"unknown evaluator type: {config.type}")


def _build_imported_evaluator(config: EvaluatorConfig) -> Evaluator:
    import_path = config.settings.get("import_path") or config.settings.get("path")
    if not import_path:
        raise ValueError("import evaluator requires settings.import_path")
    module_name, _, attr = str(import_path).rpartition(".")
    if not module_name or not attr:
        raise ValueError(f"invalid evaluator import path: {import_path}")
    module = importlib.import_module(module_name)
    factory = getattr(module, attr)
    try:
        return factory(config)
    except TypeError:
        return factory()


__all__ = [
    "Evaluator",
    "ContainsEvaluator",
    "CostEvaluator",
    "ExactMatchEvaluator",
    "JsonSchemaEvaluator",
    "MinefieldEvaluator",
    "RegexEvaluator",
    "SafetyEvaluator",
    "StateEvaluator",
    "ToolOutputEvaluator",
    "TrajectoryEvaluator",
    "TrajectoryJudgeEvaluator",
    "JudgeMetricEvaluator",
    "build_evaluator",
]
