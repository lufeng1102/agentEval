import json
from pathlib import Path

import pytest

from config import AgentConfig, AppConfig
from manifest import build_manifest, file_sha256, prompt_hash, write_manifest


def test_build_manifest_allows_missing_dataset_and_config_paths() -> None:
    config = AppConfig()

    manifest = build_manifest(None, None, config)

    assert manifest["dataset_path"] is None
    assert manifest["dataset_hash"] is None
    assert manifest["config_path"] is None
    assert manifest["config_hash"] is None
    assert manifest["agent"]["provider"] == "static"


def test_prompt_hash_includes_default_model_when_prompt_text_fields_are_absent() -> None:
    config = AppConfig()

    assert prompt_hash(config) is not None


def test_prompt_hash_changes_when_prompt_fields_change() -> None:
    base = AppConfig(agent=AgentConfig(system="A"))
    changed_system = AppConfig(agent=AgentConfig(system="B"))
    changed_response = AppConfig(agent=AgentConfig(system="A", static_response="ok"))

    assert prompt_hash(base) != prompt_hash(changed_system)
    assert prompt_hash(base) != prompt_hash(changed_response)


def test_write_manifest_currently_requires_existing_parent_directory(tmp_path: Path) -> None:
    path = tmp_path / "missing" / "manifest.json"

    with pytest.raises(FileNotFoundError):
        write_manifest(path, {"ok": True})


def test_write_manifest_writes_json_payload(tmp_path: Path) -> None:
    path = tmp_path / "manifest.json"

    write_manifest(path, {"ok": True})

    assert json.loads(path.read_text(encoding="utf-8")) == {"ok": True}


def test_file_sha256_raises_for_missing_file(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        file_sha256(tmp_path / "missing.txt")
