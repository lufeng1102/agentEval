from __future__ import annotations

from pathlib import Path
from typing import Any, Callable

from pydantic import BaseModel, Field

Redactor = Callable[[str, Any], Any]


class TraceConfig(BaseModel):
    trace_path: Path
    source: str = "sdk"
    case_id: str | None = None
    session_id: str | None = None
    agent_id: str | None = None
    agent_version: str | None = None
    user_id_hash: str | None = None
    tags: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)
    sample_rate: float = 1.0
    fail_open: bool = True
    redaction_enabled: bool = True
