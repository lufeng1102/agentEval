from __future__ import annotations

import json
from typing import Any, Literal

from pydantic import BaseModel

from adapters.contract import ADAPTER_CONTRACT_VERSION
from schemas import AgentRun

ALLOWED_SPAN_KINDS = {"llm", "tool", "retrieval", "embedding", "api", "agent", "chain", "custom"}


class ContractIssue(BaseModel):
    severity: Literal["error", "warning"]
    path: str
    message: str


def validate_agent_run_contract(run: AgentRun, *, require_adapter_metadata: bool = False) -> list[ContractIssue]:
    issues: list[ContractIssue] = []
    _validate_case(run, issues)
    _validate_tool_calls(run, issues)
    _validate_spans(run, issues)
    _validate_json_serializable("raw_response", run.raw_response, issues)
    _validate_adapter_metadata(run, issues, require_adapter_metadata=require_adapter_metadata)
    return issues


def _validate_case(run: AgentRun, issues: list[ContractIssue]) -> None:
    if not str(run.case_id or "").strip():
        issues.append(ContractIssue(severity="error", path="case_id", message="case_id must be non-empty"))
    if run.latency_ms < 0:
        issues.append(ContractIssue(severity="error", path="latency_ms", message="latency_ms must be non-negative"))


def _validate_tool_calls(run: AgentRun, issues: list[ContractIssue]) -> None:
    for index, call in enumerate(run.tool_calls):
        if not str(call.name or "").strip():
            issues.append(ContractIssue(severity="error", path=f"tool_calls[{index}].name", message="tool call name must be non-empty"))
        if not isinstance(call.input, dict):
            issues.append(ContractIssue(severity="error", path=f"tool_calls[{index}].input", message="tool call input must be a dict"))
        _validate_json_serializable(f"tool_calls[{index}].output", call.output, issues)


def _validate_spans(run: AgentRun, issues: list[ContractIssue]) -> None:
    span_ids = {span.span_id for span in run.spans}
    for index, span in enumerate(run.spans):
        if not str(span.span_id or "").strip():
            issues.append(ContractIssue(severity="error", path=f"spans[{index}].span_id", message="span_id must be non-empty"))
        if not str(span.name or "").strip():
            issues.append(ContractIssue(severity="error", path=f"spans[{index}].name", message="span name must be non-empty"))
        if str(span.kind) not in ALLOWED_SPAN_KINDS:
            issues.append(ContractIssue(severity="error", path=f"spans[{index}].kind", message=f"span kind must be one of {sorted(ALLOWED_SPAN_KINDS)}"))
        if span.parent_span_id and span.parent_span_id not in span_ids:
            issues.append(ContractIssue(severity="warning", path=f"spans[{index}].parent_span_id", message="parent_span_id does not reference a span in this run"))
        _validate_json_serializable(f"spans[{index}].input", span.input, issues)
        _validate_json_serializable(f"spans[{index}].output", span.output, issues)
        _validate_json_serializable(f"spans[{index}].attributes", span.attributes, issues)
        _validate_json_serializable(f"spans[{index}].events", span.events, issues)


def _validate_adapter_metadata(run: AgentRun, issues: list[ContractIssue], *, require_adapter_metadata: bool = False) -> None:
    adapter = run.artifacts.get("adapter") if isinstance(run.artifacts, dict) else None
    metadata_severity: Literal["error", "warning"] = "error" if require_adapter_metadata else "warning"
    if not isinstance(adapter, dict):
        issues.append(ContractIssue(severity=metadata_severity, path="artifacts.adapter", message="adapter metadata is missing"))
        return
    for key in ["contract_version", "adapter_name", "adapter_version", "framework", "capabilities"]:
        if key not in adapter:
            issues.append(ContractIssue(severity=metadata_severity, path=f"artifacts.adapter.{key}", message=f"adapter metadata missing {key}"))
    version = adapter.get("contract_version")
    if version is not None and version != ADAPTER_CONTRACT_VERSION:
        issues.append(ContractIssue(severity="warning", path="artifacts.adapter.contract_version", message=f"expected {ADAPTER_CONTRACT_VERSION}, got {version}"))
    for key in ["adapter_name", "adapter_version", "framework"]:
        if key in adapter and not str(adapter.get(key) or "").strip():
            issues.append(ContractIssue(severity=metadata_severity, path=f"artifacts.adapter.{key}", message=f"adapter metadata {key} must be a non-empty string"))
    if "capabilities" in adapter:
        capabilities = adapter.get("capabilities")
        if not isinstance(capabilities, dict):
            issues.append(ContractIssue(severity=metadata_severity, path="artifacts.adapter.capabilities", message="adapter capabilities should be a dict"))
        else:
            for key, value in capabilities.items():
                if not isinstance(value, bool):
                    issues.append(ContractIssue(severity=metadata_severity, path=f"artifacts.adapter.capabilities.{key}", message="adapter capability values must be booleans"))
    if "lossiness" in adapter:
        lossiness = adapter.get("lossiness")
        if not isinstance(lossiness, list) or not all(isinstance(item, str) for item in lossiness):
            issues.append(ContractIssue(severity=metadata_severity, path="artifacts.adapter.lossiness", message="adapter lossiness must be a list of strings"))


def _validate_json_serializable(path: str, value: Any, issues: list[ContractIssue]) -> None:
    try:
        json.dumps(value)
    except (TypeError, ValueError) as exc:
        issues.append(ContractIssue(severity="error", path=path, message=f"value must be JSON serializable: {exc}"))
