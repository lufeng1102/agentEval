from pathlib import Path

import pytest

from config import EnvironmentConfig
from environments.container import build_container_command, container_plan


def test_build_container_command_includes_workspace_image_and_limits(tmp_path: Path) -> None:
    config = EnvironmentConfig(backend="docker", container_image="python:3.12", resource_limits={"memory": "512m", "cpus": "1"})

    command = build_container_command("python -m pytest", tmp_path, config)

    assert command[:3] == ["docker", "run", "--rm"]
    assert "python:3.12" in command
    assert "--memory" in command
    assert f"{tmp_path.resolve()}:/workspace" in command


def test_build_container_command_requires_docker_backend_and_image(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="backend=docker"):
        build_container_command("pytest", tmp_path, EnvironmentConfig())
    with pytest.raises(ValueError, match="container_image"):
        build_container_command("pytest", tmp_path, EnvironmentConfig(backend="docker"))


def test_container_plan_reports_optional_backend() -> None:
    plan = container_plan(EnvironmentConfig(backend="docker", container_image="img", shard_index=0, shard_count=2))

    assert plan["enabled"] is True
    assert plan["shard_count"] == 2
