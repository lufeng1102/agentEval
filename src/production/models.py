from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field, field_validator


class ProductionEvent(BaseModel):
    event_id: str
    timestamp: str | None = None
    session_id: str | None = None
    user_id_hash: str | None = None
    agent_id: str | None = None
    agent_version: str | None = None
    model: str | None = None
    input: str | list[dict[str, Any]]
    final_output: str = ""
    messages: list[dict[str, Any]] = Field(default_factory=list)
    tool_calls: list[dict[str, Any]] = Field(default_factory=list)
    outcome: dict[str, Any] = Field(default_factory=dict)
    usage: dict[str, Any] = Field(default_factory=dict)
    latency_ms: float | None = None
    errors: list[str] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("event_id")
    @classmethod
    def event_id_must_not_be_empty(cls, value: str) -> str:
        if not str(value).strip():
            raise ValueError("event_id must not be empty")
        return value

    @field_validator("input")
    @classmethod
    def input_must_not_be_empty(cls, value: str | list[dict[str, Any]]) -> str | list[dict[str, Any]]:
        if isinstance(value, str) and not value.strip():
            raise ValueError("input must not be empty")
        if isinstance(value, list) and not value:
            raise ValueError("input messages must not be empty")
        return value


class UserFeedback(BaseModel):
    feedback_id: str
    event_id: str | None = None
    session_id: str | None = None
    timestamp: str | None = None
    rating: int | None = None
    sentiment: str | None = None
    category: str | None = None
    comment: str = ""
    user_reported_failure: bool = False
    reviewer_label: dict[str, Any] = Field(default_factory=dict)
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("feedback_id")
    @classmethod
    def feedback_id_must_not_be_empty(cls, value: str) -> str:
        if not str(value).strip():
            raise ValueError("feedback_id must not be empty")
        return value


class JoinedProductionRecord(BaseModel):
    event: ProductionEvent | None = None
    feedback: list[UserFeedback] = Field(default_factory=list)
    matched: bool = True
