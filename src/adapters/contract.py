from __future__ import annotations

from typing import Any, Protocol

from pydantic import BaseModel, Field

from schemas import AgentRun, EvalCase, RunContext

ADAPTER_CONTRACT_VERSION = "agenteval.adapter.v1"


class AgentAdapterV1(Protocol):
    async def run(self, case: EvalCase, context: RunContext) -> AgentRun:
        """Run one evaluation case and return a normalized AgentRun."""


class AdapterCapabilities(BaseModel):
    messages: bool = False
    tool_calls: bool = False
    spans: bool = False
    usage: bool = False
    retrieval: bool = False
    multi_agent: bool = False


def adapter_metadata(
    adapter_name: str,
    *,
    adapter_version: str = "0.1.0",
    framework: str | None = None,
    framework_version: str | None = None,
    capabilities: AdapterCapabilities | dict[str, bool] | None = None,
    lossiness: list[str] | None = None,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "contract_version": ADAPTER_CONTRACT_VERSION,
        "adapter_name": adapter_name,
        "adapter_version": adapter_version,
        "framework": framework or adapter_name,
        "capabilities": (capabilities if isinstance(capabilities, AdapterCapabilities) else AdapterCapabilities(**(capabilities or {}))).model_dump(),
    }
    if framework_version:
        payload["framework_version"] = framework_version
    if lossiness:
        payload["lossiness"] = [str(item) for item in lossiness]
    if extra:
        payload.update(extra)
    return payload
