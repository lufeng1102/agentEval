from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, Field

from schemas import EvalDataset, ToolCall


class AgentConfig(BaseModel):
    provider: str = "static"
    model: str = "claude-opus-4-8"
    system: str | None = None
    temperature: float | None = None
    max_tokens: int = 16000
    output_config: dict[str, Any] | None = None
    thinking: dict[str, Any] | None = None
    cache_control: dict[str, Any] | None = None
    cache_system_prompt: bool = False
    prompt_version: str | None = None
    static_response: str | None = None
    static_tool_calls: list[ToolCall] = Field(default_factory=list)
    static_latency_ms: float | None = None
    static_artifacts: dict[str, Any] = Field(default_factory=dict)


class RunnerConfig(BaseModel):
    concurrency: int = 1
    timeout_seconds: float = 120
    retries: int = 0
    repeats: int = 1


class EvaluatorConfig(BaseModel):
    type: str
    judge_model: str = "claude-opus-4-8"
    threshold: float = 0.7
    settings: dict[str, Any] = Field(default_factory=dict)


class ReportConfig(BaseModel):
    formats: list[str] = Field(default_factory=lambda: ["json", "markdown"])


class AppConfig(BaseModel):
    agent: AgentConfig = Field(default_factory=AgentConfig)
    runner: RunnerConfig = Field(default_factory=RunnerConfig)
    evaluators: list[EvaluatorConfig] = Field(default_factory=lambda: [EvaluatorConfig(type="contains")])
    report: ReportConfig = Field(default_factory=ReportConfig)


def load_yaml(path: str | Path) -> dict[str, Any]:
    with Path(path).open("r", encoding="utf-8") as file:
        data = yaml.safe_load(file) or {}
    if not isinstance(data, dict):
        raise ValueError(f"YAML file must contain an object: {path}")
    return data


def load_config(path: str | Path) -> AppConfig:
    return AppConfig.model_validate(load_yaml(path))


def load_dataset(path: str | Path) -> EvalDataset:
    return EvalDataset.model_validate(load_yaml(path))
