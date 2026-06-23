from __future__ import annotations

import json
from pathlib import Path

import pytest

from hosted import HostedIngestionService, IngestionConflict, LocalHostedStorage
from schemas import AgentRun, EvalResult


def write_run(path: Path, *, run_id: str = "run-key", pass_rate: float = 1.0, output: str = "ok") -> Path:
    path.mkdir(parents=True, exist_ok=True)
    (path / "manifest.json").write_text(json.dumps({"run_id": run_id, "agent": {"provider": "static"}}), encoding="utf-8")
    (path / "report.json").write_text(json.dumps({"summary": {"pass_rate": pass_rate, "avg_score": pass_rate}, "cases": [], "runs": [], "results": []}), encoding="utf-8")
    (path / "traces.jsonl").write_text(AgentRun(case_id="c1", final_output=output).model_dump_json() + "\n", encoding="utf-8")
    (path / "results.jsonl").write_text(EvalResult(case_id="c1", evaluator="contains", score=pass_rate, passed=pass_rate >= 1).model_dump_json() + "\n", encoding="utf-8")
    return path


def test_ingest_run_directory_indexes_artifacts(tmp_path: Path) -> None:
    service = HostedIngestionService(LocalHostedStorage(tmp_path / "hosted"), dashboard_base_url="https://example")

    result = service.ingest_run_directory(write_run(tmp_path / "run"), project_id="proj")

    assert result.status == "indexed"
    assert result.already_exists is False
    assert result.dashboard_url == f"https://example/runs/{result.run_id}"
    assert {artifact.kind for artifact in result.artifacts} == {"manifest", "traces_jsonl", "results_jsonl", "report_json"}
    stored = service.get_run(result.run_id)
    assert stored is not None
    assert stored.project_id == "proj"
    assert stored.summary["pass_rate"] == 1.0
    for artifact in stored.artifacts:
        assert Path(artifact.storage_path).exists()
        assert artifact.size_bytes > 0
        assert artifact.sha256


def test_idempotent_reupload_returns_existing_run(tmp_path: Path) -> None:
    service = HostedIngestionService(LocalHostedStorage(tmp_path / "hosted"))
    run_dir = write_run(tmp_path / "run")

    first = service.ingest_run_directory(run_dir, project_id="proj")
    second = service.ingest_run_directory(run_dir, project_id="proj")

    assert second.already_exists is True
    assert second.run_id == first.run_id


def test_conflict_on_same_run_key_with_different_artifacts(tmp_path: Path) -> None:
    service = HostedIngestionService(LocalHostedStorage(tmp_path / "hosted"))
    first_dir = write_run(tmp_path / "run-a", run_id="same", output="a")
    second_dir = write_run(tmp_path / "run-b", run_id="same", output="b")

    service.ingest_run_directory(first_dir, project_id="proj")

    with pytest.raises(IngestionConflict):
        service.ingest_run_directory(second_dir, project_id="proj")


def test_overwrite_same_run_key_replaces_run(tmp_path: Path) -> None:
    service = HostedIngestionService(LocalHostedStorage(tmp_path / "hosted"))
    first_dir = write_run(tmp_path / "run-a", run_id="same", output="a", pass_rate=1.0)
    second_dir = write_run(tmp_path / "run-b", run_id="same", output="b", pass_rate=0.5)

    first = service.ingest_run_directory(first_dir, project_id="proj")
    second = service.ingest_run_directory(second_dir, project_id="proj", overwrite=True)

    assert second.run_id == first.run_id
    assert second.already_exists is False
    stored = service.get_run(first.run_id)
    assert stored is not None
    assert stored.summary["pass_rate"] == 0.5


def test_explicit_idempotency_key_controls_existing_detection(tmp_path: Path) -> None:
    service = HostedIngestionService(LocalHostedStorage(tmp_path / "hosted"))
    run_dir = write_run(tmp_path / "run", run_id="same")

    first = service.ingest_run_directory(run_dir, project_id="proj", idempotency_key="fixed")
    second = service.ingest_run_directory(run_dir, project_id="proj", idempotency_key="fixed")

    assert second.already_exists is True
    assert first.run_id == second.run_id


def test_missing_artifacts_raise(tmp_path: Path) -> None:
    service = HostedIngestionService(LocalHostedStorage(tmp_path / "hosted"))
    empty = tmp_path / "empty"
    empty.mkdir()

    with pytest.raises(FileNotFoundError):
        service.ingest_run_directory(empty)
