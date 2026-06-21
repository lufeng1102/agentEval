from __future__ import annotations

from typing import Any

from schemas import ChatMessage, EvalCase, Usage


def case_messages(case: EvalCase) -> list[ChatMessage]:
    if isinstance(case.input, str):
        return [ChatMessage(role="user", content=case.input)]
    return list(case.input)


def case_tools(case: EvalCase) -> list[dict[str, Any]]:
    tools = []
    for tool in case.scenario.get("tools", []) or []:
        name = str(tool.get("name", ""))
        if not name:
            continue
        tools.append(
            {
                "name": name,
                "description": str(tool.get("description") or f"Mock tool {name}"),
                "input_schema": tool.get("input_schema") or {"type": "object", "properties": {}},
            }
        )
    return tools


def merge_usage(left: Usage, right: Usage) -> Usage:
    return Usage(
        input_tokens=left.input_tokens + right.input_tokens,
        output_tokens=left.output_tokens + right.output_tokens,
        cache_creation_input_tokens=left.cache_creation_input_tokens + right.cache_creation_input_tokens,
        cache_read_input_tokens=left.cache_read_input_tokens + right.cache_read_input_tokens,
    )


def extract_text(content: list[Any]) -> str:
    parts: list[str] = []
    for block in content:
        if getattr(block, "type", None) == "text":
            parts.append(getattr(block, "text", ""))
    return "".join(parts).strip()


def extract_usage(response: Any) -> Usage:
    usage = getattr(response, "usage", None)
    if usage is None:
        return Usage()
    return Usage(
        input_tokens=getattr(usage, "input_tokens", 0) or 0,
        output_tokens=getattr(usage, "output_tokens", 0) or 0,
        cache_creation_input_tokens=getattr(usage, "cache_creation_input_tokens", 0) or 0,
        cache_read_input_tokens=getattr(usage, "cache_read_input_tokens", 0) or 0,
    )
