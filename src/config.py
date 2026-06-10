from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, Field

from schemas import EvalDataset, ToolCall
from expected_files import resolve_expected_files


class AgentConfig(BaseModel):
    provider: str = "static"
    id: str | None = None
    version: str | None = None
    model: str = "claude-opus-4-8"
    system: str | None = None
    temperature: float | None = None
    max_tokens: int = 16000
    output_config: dict[str, Any] | None = None
    thinking: dict[str, Any] | None = None
    cache_control: dict[str, Any] | None = None
    cache_system_prompt: bool = False
    prompt_version: str | None = None
    toolset_version: str | None = None
    policy_version: str | None = None
    memory_version: str | None = None
    component_hashes: dict[str, str] = Field(default_factory=dict)
    static_response: str | None = None
    static_tool_calls: list[ToolCall] = Field(default_factory=list)
    static_latency_ms: float | None = None
    static_artifacts: dict[str, Any] = Field(default_factory=dict)
    settings: dict[str, Any] = Field(default_factory=dict)


class RunnerConfig(BaseModel):
    concurrency: int = 1
    timeout_seconds: float = 120
    retries: int = 0
    repeats: int = 1


class EnvironmentConfig(BaseModel):
    type: str = "none"
    fixture: Path | None = None
    isolation: str = "copy"
    reset_between_trials: bool = True
    keep_on_failure: bool = True
    include_patterns: list[str] = Field(default_factory=lambda: ["**/*"])
    exclude_patterns: list[str] = Field(default_factory=lambda: [".git/**", "__pycache__/**", ".pytest_cache/**", "node_modules/**"])
    protected_paths: list[str] = Field(default_factory=list)
    setup_commands: list[str] = Field(default_factory=list)
    test_commands: list[str] = Field(default_factory=list)
    teardown_commands: list[str] = Field(default_factory=list)
    setup_queries: list[Any] = Field(default_factory=list)
    test_queries: list[Any] = Field(default_factory=list)
    teardown_queries: list[Any] = Field(default_factory=list)
    base_url: str | None = None
    setup_checks: list[dict[str, Any]] = Field(default_factory=list)
    test_checks: list[dict[str, Any]] = Field(default_factory=list)
    teardown_checks: list[dict[str, Any]] = Field(default_factory=list)
    database_path: str | None = None
    browser_timeout_seconds: float = 30
    browser_headless: bool = True
    browser_viewport: dict[str, Any] = Field(default_factory=lambda: {"width": 1280, "height": 720})
    browser_screenshot: bool = False
    command_timeout_seconds: float = 120
    max_command_output_chars: int = 20000
    retain_workspaces: str = "always"


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
    environment: EnvironmentConfig = Field(default_factory=EnvironmentConfig)
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
    payload = _load_dataset_payload(Path(path))
    return EvalDataset.model_validate(payload)


def _load_dataset_payload(path: Path, seen: set[Path] | None = None) -> dict[str, Any]:
    seen = seen or set()
    if path.is_dir():
        files = sorted([*path.glob("*.yaml"), *path.glob("*.yml")])
        return _merge_dataset_payloads([_load_dataset_payload(file, seen) for file in files], sources=files, base_dir=path)

    resolved = path.resolve()
    if resolved in seen:
        raise ValueError(f"recursive dataset include: {path}")
    seen.add(resolved)
    payload = load_yaml(path)
    base_cases = list(payload.get("cases") or [])
    include_payloads = []
    for include in payload.get("includes") or []:
        include_paths = sorted(path.parent.glob(str(include)))
        if not include_paths:
            raise ValueError(f"dataset include matched no files: {include}")
        include_payloads.extend(_load_dataset_payload(include_path, seen) for include_path in include_paths)
    merged = _merge_dataset_payloads([{"metadata": payload.get("metadata") or {}, "cases": base_cases}, *include_payloads], sources=[path], base_dir=path.parent)
    seen.remove(resolved)
    return merged


def _merge_dataset_payloads(payloads: list[dict[str, Any]], sources: list[Path] | None = None, base_dir: Path | None = None) -> dict[str, Any]:
    metadata: dict[str, Any] = {}
    cases: list[dict[str, Any]] = []
    case_ids: set[str] = set()
    all_sources: list[str] = []
    base_dir = base_dir or Path.cwd()
    for payload in payloads:
        metadata.update(payload.get("metadata") or {})
        for source in payload.get("metadata", {}).get("sources", []) or []:
            all_sources.append(str(source))
        for case in payload.get("cases") or []:
            if isinstance(case, dict):
                case = dict(case)
                case["expected"] = resolve_expected_files(case.get("expected") or {}, base_dir)
            case_id = str(case.get("id")) if isinstance(case, dict) else ""
            if case_id in case_ids:
                raise ValueError(f"duplicate case id: {case_id}")
            case_ids.add(case_id)
            cases.append(case)
    if sources:
        all_sources.extend(str(source) for source in sources)
    if all_sources:
        deduped_sources = list(dict.fromkeys(all_sources))
        metadata["sources"] = deduped_sources
    return {"metadata": metadata, "cases": cases}
