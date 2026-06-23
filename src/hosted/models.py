from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

RunStatus = Literal["uploading", "uploaded", "indexed", "failed"]
ArtifactKind = Literal["manifest", "traces_jsonl", "results_jsonl", "report_json", "report_md", "report_html", "export_jsonl", "other"]


class RunArtifact(BaseModel):
    id: str
    run_id: str
    kind: ArtifactKind
    path: str
    content_type: str
    size_bytes: int
    sha256: str
    storage_path: str
    metadata: dict[str, Any] = Field(default_factory=dict)


class HostedRun(BaseModel):
    id: str
    project_id: str
    run_key: str
    idempotency_key: str
    status: RunStatus = "indexed"
    source: str = "cli_upload"
    manifest: dict[str, Any] = Field(default_factory=dict)
    summary: dict[str, Any] = Field(default_factory=dict)
    artifacts: list[RunArtifact] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


class IngestionResult(BaseModel):
    run_id: str
    status: RunStatus
    already_exists: bool = False
    dashboard_url: str | None = None
    artifacts: list[RunArtifact] = Field(default_factory=list)


class IngestionConflict(Exception):
    def __init__(self, run_key: str):
        super().__init__(f"run_key already exists with different artifacts: {run_key}")
        self.run_key = run_key
