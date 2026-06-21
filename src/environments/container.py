from __future__ import annotations

from pathlib import Path
from typing import Any

from config import EnvironmentConfig


def build_container_command(command: str, workspace: str | Path, config: EnvironmentConfig) -> list[str]:
    """Build a Docker command for optional containerized environment execution."""
    if config.backend != "docker":
        raise ValueError("container command requires environment.backend=docker")
    if not config.container_image:
        raise ValueError("docker backend requires environment.container_image")
    workspace_path = Path(workspace).resolve()
    args = ["docker", "run", "--rm", "-v", f"{workspace_path}:/workspace", "-w", "/workspace"]
    limits = config.resource_limits or {}
    if limits.get("memory"):
        args.extend(["--memory", str(limits["memory"])])
    if limits.get("cpus"):
        args.extend(["--cpus", str(limits["cpus"])])
    args.extend([config.container_image, "sh", "-lc", command])
    return args


def container_plan(config: EnvironmentConfig) -> dict[str, Any]:
    return {
        "backend": config.backend,
        "container_image": config.container_image,
        "resource_limits": dict(config.resource_limits),
        "shard_index": config.shard_index,
        "shard_count": config.shard_count,
        "enabled": config.backend == "docker",
    }
