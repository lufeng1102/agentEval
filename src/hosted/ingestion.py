from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from hosted.models import HostedRun, IngestionConflict, IngestionResult, RunArtifact
from hosted.storage import LocalHostedStorage, read_json, sha256_parts

ARTIFACTS = {
    "manifest.json": ("manifest", "application/json"),
    "traces.jsonl": ("traces_jsonl", "application/jsonl"),
    "results.jsonl": ("results_jsonl", "application/jsonl"),
    "report.json": ("report_json", "application/json"),
    "report.md": ("report_md", "text/markdown"),
    "report.html": ("report_html", "text/html"),
}


class HostedIngestionService:
    def __init__(self, storage: LocalHostedStorage, *, dashboard_base_url: str | None = None):
        self.storage = storage
        self.dashboard_base_url = dashboard_base_url

    def ingest_run_directory(
        self,
        run_dir: str | Path,
        *,
        project_id: str = "default",
        run_key: str | None = None,
        idempotency_key: str | None = None,
        overwrite: bool = False,
        source: str = "cli_upload",
    ) -> IngestionResult:
        path = Path(run_dir)
        artifact_paths = _artifact_paths(path)
        if not artifact_paths:
            raise FileNotFoundError(f"no AgentEval artifacts found in {path}")
        manifest = read_json(path / "manifest.json") if (path / "manifest.json").exists() else {}
        report = read_json(path / "report.json") if (path / "report.json").exists() else {}
        summary = report.get("summary", {}) if isinstance(report.get("summary", {}), dict) else {}
        run_key = run_key or str(manifest.get("run_id") or manifest.get("id") or path.name)
        idempotency_key = idempotency_key or sha256_parts(artifact_paths)
        existing = self.storage.get_run_by_key(project_id, run_key)
        if existing:
            if existing.idempotency_key == idempotency_key:
                return IngestionResult(run_id=existing.id, status=existing.status, already_exists=True, dashboard_url=self._dashboard_url(existing.id), artifacts=existing.artifacts)
            if not overwrite:
                raise IngestionConflict(run_key)
        run_id = existing.id if existing and overwrite else _run_id(project_id, run_key, idempotency_key)
        artifacts = [self._store(path, run_id, file_path) for file_path in artifact_paths]
        hosted_run = HostedRun(id=run_id, project_id=project_id, run_key=run_key, idempotency_key=idempotency_key, status="indexed", source=source, manifest=manifest, summary=summary, artifacts=artifacts, metadata={"source_run_dir": str(path)})
        self.storage.save_run(hosted_run)
        return IngestionResult(run_id=run_id, status=hosted_run.status, already_exists=False, dashboard_url=self._dashboard_url(run_id), artifacts=artifacts)

    def get_run(self, run_id: str) -> HostedRun | None:
        return self.storage.get_run(run_id)

    def _store(self, run_dir: Path, run_id: str, artifact_path: Path) -> RunArtifact:
        kind, content_type = ARTIFACTS.get(artifact_path.name, ("other", "application/octet-stream"))
        return self.storage.store_artifact(run_id, artifact_path, kind=kind, path_name=artifact_path.name, content_type=content_type)

    def _dashboard_url(self, run_id: str) -> str | None:
        if not self.dashboard_base_url:
            return None
        return f"{self.dashboard_base_url.rstrip('/')}/runs/{run_id}"


def _artifact_paths(run_dir: Path) -> list[Path]:
    return [run_dir / name for name in ARTIFACTS if (run_dir / name).exists()]


def _run_id(project_id: str, run_key: str, idempotency_key: str) -> str:
    safe_project = _safe(project_id)
    safe_key = _safe(run_key)
    return f"run_{safe_project}_{safe_key}_{idempotency_key[:12]}"


def _safe(value: str) -> str:
    return "".join(ch if ch.isalnum() or ch in {"-", "_"} else "-" for ch in value).strip("-") or "default"
