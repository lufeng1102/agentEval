from __future__ import annotations

from typing import Any, Callable

SENSITIVE_KEYS = {"api_key", "authorization", "password", "secret", "token", "cookie", "set-cookie"}


def redact_value(value: Any, *, redactor: Callable[[str, Any], Any] | None = None, path: str = "") -> Any:
    if redactor is not None:
        value = redactor(path, value)
    if isinstance(value, dict):
        redacted = {}
        for key, item in value.items():
            child_path = f"{path}.{key}" if path else str(key)
            if str(key).lower() in SENSITIVE_KEYS:
                redacted[key] = "[REDACTED]"
            else:
                redacted[key] = redact_value(item, redactor=redactor, path=child_path)
        return redacted
    if isinstance(value, list):
        return [redact_value(item, redactor=redactor, path=f"{path}[{index}]") for index, item in enumerate(value)]
    return value
