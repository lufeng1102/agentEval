from __future__ import annotations

from config import EnvironmentConfig
from environments.database import PreparedDatabaseEnvironment, prepare_database_environment
from environments.filesystem import PreparedEnvironment, prepare_filesystem_environment
from environments.http_api import PreparedHttpApiEnvironment, prepare_http_api_environment
from schemas import EvalCase

PreparedAnyEnvironment = PreparedEnvironment | PreparedDatabaseEnvironment | PreparedHttpApiEnvironment


def environment_enabled(config: EnvironmentConfig, case: EvalCase | None = None) -> bool:
    return _merged_environment_type(config, case) != "none"


def prepare_environment(case: EvalCase, repeat_index: int, output_dir, config: EnvironmentConfig) -> PreparedAnyEnvironment:
    env_type = _merged_environment_type(config, case)
    if env_type == "filesystem":
        return prepare_filesystem_environment(case, repeat_index, output_dir, config)
    if env_type == "database":
        return prepare_database_environment(case, repeat_index, output_dir, config)
    if env_type == "http_api":
        return prepare_http_api_environment(case, repeat_index, output_dir, config)
    raise ValueError(f"unsupported environment type: {env_type}")


def _merged_environment_type(config: EnvironmentConfig, case: EvalCase | None = None) -> str:
    env_type = config.type
    if case is not None and case.environment:
        env_type = str(case.environment.get("type", env_type))
    return env_type
