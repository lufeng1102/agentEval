from __future__ import annotations

from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


MessageRole = Literal["user", "assistant", "system", "tool"]
ToolInputMatchMode = Literal["exact", "contains"]
TrajectoryMatchMode = Literal["required", "strict", "unordered", "subset", "superset"]
SpanKind = Literal["llm", "tool", "retrieval", "embedding", "api", "agent", "chain", "custom"]
SpanStatus = Literal["ok", "error", "unset"]


class ChatMessage(BaseModel):
    role: MessageRole
    content: str | list[dict[str, Any]]


class EvalCase(BaseModel):
    """A single evaluation case from a dataset."""

    id: str
    input: str | list[ChatMessage]
    name: str | None = None
    expected: dict[str, Any] = Field(default_factory=dict)
    scenario: dict[str, Any] = Field(default_factory=dict)
    environment: dict[str, Any] = Field(default_factory=dict)
    rubric: str | None = None
    tags: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)
    reference: dict[str, Any] = Field(default_factory=dict)
    timeout_seconds: float | None = None
    evaluators: list[str] | None = None

    @field_validator("id")
    @classmethod
    def id_must_not_be_empty(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("case id must not be empty")
        return value

    @field_validator("input")
    @classmethod
    def input_must_not_be_empty(cls, value: str | list[ChatMessage]) -> str | list[ChatMessage]:
        if isinstance(value, str) and not value.strip():
            raise ValueError("case input must not be empty")
        if isinstance(value, list) and not value:
            raise ValueError("case input messages must not be empty")
        return value


class ExpectedToolCall(BaseModel):
    name: str
    input: dict[str, Any] = Field(default_factory=dict)
    match_mode: ToolInputMatchMode = "contains"


class Milestone(BaseModel):
    id: str
    required_tool: str | None = None
    required_output: str | None = None
    depends_on: list[str] = Field(default_factory=list)


class StateAssertion(BaseModel):
    path: str
    value: Any
    match_mode: ToolInputMatchMode = "exact"


class Minefield(BaseModel):
    id: str
    forbidden_tool: str | None = None
    forbidden_output_regex: str | None = None
    forbidden_tool_argument: dict[str, Any] | None = None
    forbidden_state: dict[str, Any] | None = None


class TrajectoryPolicy(BaseModel):
    match_mode: TrajectoryMatchMode = "required"
    check_arguments: bool = False
    allow_extra_tools: bool = True


class EvalDataset(BaseModel):
    cases: list[EvalCase]
    metadata: dict[str, Any] = Field(default_factory=dict)


class Usage(BaseModel):
    input_tokens: int = 0
    output_tokens: int = 0
    cache_creation_input_tokens: int = 0
    cache_read_input_tokens: int = 0

    @property
    def total_input_tokens(self) -> int:
        return self.input_tokens + self.cache_creation_input_tokens + self.cache_read_input_tokens


class ToolCall(BaseModel):
    name: str
    input: dict[str, Any] = Field(default_factory=dict)
    output: Any = None
    error: str | None = None


class TraceSpan(BaseModel):
    span_id: str
    trace_id: str | None = None
    parent_span_id: str | None = None
    name: str
    kind: SpanKind | str = "custom"
    start_time: str | None = None
    end_time: str | None = None
    latency_ms: float | None = None
    status: SpanStatus | str = "unset"
    input: Any = None
    output: Any = None
    error: str | None = None
    attributes: dict[str, Any] = Field(default_factory=dict)
    events: list[dict[str, Any]] = Field(default_factory=list)

    @field_validator("span_id", "name")
    @classmethod
    def span_fields_must_not_be_empty(cls, value: str) -> str:
        if not str(value).strip():
            raise ValueError("span id and name must not be empty")
        return value


class AgentTrace(BaseModel):
    trace_id: str
    case_id: str | None = None
    session_id: str | None = None
    user_id_hash: str | None = None
    agent_id: str | None = None
    agent_version: str | None = None
    source: str | None = None
    input: str | list[ChatMessage] | None = None
    final_output: str = ""
    messages: list[ChatMessage] = Field(default_factory=list)
    spans: list[TraceSpan] = Field(default_factory=list)
    tool_calls: list[ToolCall] = Field(default_factory=list)
    usage: Usage = Field(default_factory=Usage)
    latency_ms: float = 0
    errors: list[str] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("trace_id")
    @classmethod
    def trace_id_must_not_be_empty(cls, value: str) -> str:
        if not str(value).strip():
            raise ValueError("trace_id must not be empty")
        return value


class AgentRun(BaseModel):
    case_id: str
    repeat_index: int = 0
    messages: list[ChatMessage] = Field(default_factory=list)
    final_output: str = ""
    tool_calls: list[ToolCall] = Field(default_factory=list)
    spans: list[TraceSpan] = Field(default_factory=list)
    latency_ms: float = 0
    usage: Usage = Field(default_factory=Usage)
    errors: list[str] = Field(default_factory=list)
    raw_response: dict[str, Any] | None = None
    artifacts: dict[str, Any] = Field(default_factory=dict)


class EvalResult(BaseModel):
    case_id: str
    evaluator: str
    repeat_index: int = 0
    score: float = Field(ge=0, le=1)
    passed: bool
    metrics: dict[str, Any] = Field(default_factory=dict)
    judgements: list[dict[str, Any]] = Field(default_factory=list)
    failure_reason: str | None = None
    failure_type: str | None = None
    artifacts: dict[str, Any] = Field(default_factory=dict)


class RunContext(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)

    output_dir: Path
    config: dict[str, Any] = Field(default_factory=dict)
    environment: dict[str, Any] | None = None
