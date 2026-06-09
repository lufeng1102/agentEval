from __future__ import annotations

from typing import Any

from pydantic import AliasChoices, BaseModel, Field


class FileSnapshot(BaseModel):
    path: str
    sha256: str
    size_bytes: int


class EnvironmentSnapshot(BaseModel):
    root_hash: str
    files: dict[str, FileSnapshot] = Field(default_factory=dict)


class EnvironmentDiff(BaseModel):
    created: list[str] = Field(default_factory=list)
    modified: list[str] = Field(default_factory=list)
    deleted: list[str] = Field(default_factory=list)
    protected_path_violations: list[str] = Field(default_factory=list)


class CommandResult(BaseModel):
    phase: str
    command: str
    exit_code: int | None = None
    stdout: str = ""
    stderr: str = ""
    duration_ms: int = 0
    timed_out: bool = False


class DatabaseQueryResult(BaseModel):
    phase: str
    query: str
    params: list[Any] = Field(default_factory=list)
    rows: list[dict[str, Any]] = Field(default_factory=list)
    row_count: int = 0
    error: str | None = None
    duration_ms: int = 0


class HttpCheckResult(BaseModel):
    phase: str
    method: str = "GET"
    url: str
    status_code: int | None = None
    response_body: str = ""
    json_body: Any = Field(default=None, serialization_alias="json", validation_alias=AliasChoices("json", "json_body"))
    error: str | None = None
    duration_ms: int = 0


class EnvironmentSessionRecord(BaseModel):
    case_id: str
    repeat_index: int
    type: str
    fixture: str | None = None
    root: str
    before: EnvironmentSnapshot | None = None
    after: EnvironmentSnapshot | None = None
    diff: EnvironmentDiff | None = None
    commands: list[CommandResult] = Field(default_factory=list)
    database: list[DatabaseQueryResult] = Field(default_factory=list)
    http: list[HttpCheckResult] = Field(default_factory=list)
