from __future__ import annotations

from typing import Any


def get_path(data: Any, path: str) -> tuple[bool, Any]:
    current = data
    if not path:
        return True, current
    for part in path.split("."):
        if isinstance(current, dict) and part in current:
            current = current[part]
        elif isinstance(current, list) and part.isdigit() and int(part) < len(current):
            current = current[int(part)]
        else:
            return False, None
    return True, current


def value_matches(expected: Any, actual: Any, match_mode: str = "exact") -> bool:
    if match_mode == "exact":
        return actual == expected
    return contains_value(expected, actual)


def contains_value(expected: Any, actual: Any) -> bool:
    if isinstance(expected, dict):
        if not isinstance(actual, dict):
            return False
        return all(key in actual and contains_value(value, actual[key]) for key, value in expected.items())
    if isinstance(expected, list):
        if not isinstance(actual, list):
            return False
        return all(any(contains_value(expected_item, actual_item) for actual_item in actual) for expected_item in expected)
    if isinstance(expected, str) and isinstance(actual, str):
        return expected in actual
    return actual == expected
