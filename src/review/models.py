from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator

Priority = Literal["low", "medium", "high", "critical"]


class ReviewItem(BaseModel):
    review_id: str
    run_dir: str
    case_id: str
    repeat_index: int = 0
    priority: Priority = "medium"
    strategies: list[str] = Field(default_factory=list)
    input: Any = None
    expected: dict[str, Any] = Field(default_factory=dict)
    rubric: str | None = None
    tags: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)
    agent_output: str = ""
    messages: list[dict[str, Any]] = Field(default_factory=list)
    tool_calls: list[dict[str, Any]] = Field(default_factory=list)
    environment: dict[str, Any] = Field(default_factory=dict)
    results: list[dict[str, Any]] = Field(default_factory=list)
    suggested_reason: str | None = None


class HumanLabel(BaseModel):
    review_id: str | None = None
    case_id: str
    repeat_index: int = 0
    human_passed: bool
    human_score: float = Field(ge=0, le=1)
    human_failure_type: str | None = None
    human_reason: str = ""
    rubric_dimension_scores: dict[str, float] = Field(default_factory=dict)
    reviewer: str | None = None
    reviewed_at: str | None = None

    @field_validator("case_id")
    @classmethod
    def case_id_must_not_be_empty(cls, value: str) -> str:
        if not str(value).strip():
            raise ValueError("case_id must not be empty")
        return value


class HumanReviewRecord(BaseModel):
    item: ReviewItem
    label: HumanLabel | None = None
    automated_passed: bool | None = None
    automated_score: float | None = None
    mismatch: str | None = None


def automated_summary(results: list[dict[str, Any]]) -> tuple[bool | None, float | None]:
    if not results:
        return None, None
    return all(bool(result.get("passed")) for result in results), sum(float(result.get("score", 0) or 0) for result in results) / len(results)
