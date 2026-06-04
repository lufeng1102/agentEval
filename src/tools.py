from __future__ import annotations

from copy import deepcopy
from typing import Any

from evaluators.json_schema import _validate_schema
from evaluators.matching import get_path
from schemas import ToolCall


class MockToolRuntime:
    """Applies configured mock tool behavior to tool calls by name."""

    def __init__(self, tools: list[dict[str, Any]], initial_state: dict[str, Any] | None = None):
        self.tools = {str(tool.get("name")): tool for tool in tools}
        self.state = deepcopy(initial_state or {})

    @classmethod
    def from_case(cls, case_tools: list[dict[str, Any]] | None, initial_state: dict[str, Any] | None = None) -> "MockToolRuntime":
        return cls(case_tools or [], initial_state=initial_state)

    def apply(self, calls: list[ToolCall]) -> tuple[list[ToolCall], dict[str, Any]]:
        updated: list[ToolCall] = []
        for call in calls:
            tool = self.tools.get(call.name)
            if not tool:
                updated.append(call)
                continue
            data = call.model_copy(deep=True)
            errors = _validate_input(tool.get("input_schema"), data.input)
            if errors:
                data.error = "; ".join(errors)
                updated.append(data)
                continue
            if "mock_output" in tool:
                data.output = tool.get("mock_output")
            for update in tool.get("state_updates", []) or []:
                _apply_state_update(self.state, update, data)
            updated.append(data)
        return updated, self.state


def _validate_input(schema: dict[str, Any] | None, value: dict[str, Any]) -> list[str]:
    if not schema:
        return []
    return _validate_schema(value, schema, "$input")


def _apply_state_update(state: dict[str, Any], update: dict[str, Any], call: ToolCall) -> None:
    raw_path = str(update.get("path", ""))
    if not raw_path:
        return
    value = _resolve_templates(update.get("value"), call)
    path = _resolve_templates(raw_path, call)
    _set_path(state, str(path), value)


def _resolve_templates(value: Any, call: ToolCall) -> Any:
    if isinstance(value, str):
        result = value
        for key, item in call.input.items():
            result = result.replace("${input." + key + "}", str(item))
        return result
    return value


def _set_path(data: dict[str, Any], path: str, value: Any) -> None:
    parts = path.split(".")
    current = data
    for part in parts[:-1]:
        current = current.setdefault(part, {})
    current[parts[-1]] = value
