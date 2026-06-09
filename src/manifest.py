from __future__ import annotations

import hashlib
import json
import platform
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from config import AppConfig


def build_manifest(dataset_path: str | Path | None, config_path: str | Path | None, config: AppConfig) -> dict[str, Any]:
    return {
        "created_at": datetime.now(timezone.utc).isoformat(),
        "dataset_path": str(dataset_path) if dataset_path else None,
        "dataset_hash": file_sha256(dataset_path) if dataset_path else None,
        "config_path": str(config_path) if config_path else None,
        "config_hash": file_sha256(config_path) if config_path else None,
        "prompt_version": config.agent.prompt_version,
        "prompt_hash": prompt_hash(config),
        "agent_version": agent_version_snapshot(config),
        "agenteval_version": "0.1.0",
        "python_version": platform.python_version(),
        "platform": platform.platform(),
        "agent": config.agent.model_dump(mode="json"),
        "runner": config.runner.model_dump(mode="json"),
        "evaluators": [item.model_dump(mode="json") for item in config.evaluators],
        "report": config.report.model_dump(mode="json"),
    }


def agent_version_snapshot(config: AppConfig) -> dict[str, Any]:
    return {
        "agent_id": config.agent.id,
        "version": config.agent.version,
        "provider": config.agent.provider,
        "model": config.agent.model,
        "prompt_version": config.agent.prompt_version,
        "toolset_version": config.agent.toolset_version,
        "policy_version": config.agent.policy_version,
        "memory_version": config.agent.memory_version,
        "component_hashes": dict(config.agent.component_hashes),
    }


def write_manifest(path: str | Path, manifest: dict[str, Any]) -> None:
    Path(path).write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")


def prompt_hash(config: AppConfig) -> str | None:
    prompt_parts = {
        "system": config.agent.system,
        "static_response": config.agent.static_response,
        "model": config.agent.model,
    }
    if not any(value is not None for value in prompt_parts.values()):
        return None
    rendered = json.dumps(prompt_parts, ensure_ascii=False, sort_keys=True)
    return hashlib.sha256(rendered.encode("utf-8")).hexdigest()


def file_sha256(path: str | Path) -> str:
    hasher = hashlib.sha256()
    with Path(path).open("rb") as file:
        for chunk in iter(lambda: file.read(1024 * 1024), b""):
            hasher.update(chunk)
    return hasher.hexdigest()
