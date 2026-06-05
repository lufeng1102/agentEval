from __future__ import annotations

from pathlib import Path
from typing import Any


def resolve_expected_files(expected: dict[str, Any], base_dir: str | Path) -> dict[str, Any]:
    """Return expected with *_file references resolved relative to base_dir."""
    resolved = dict(expected)
    base = Path(base_dir)
    mappings = {
        "answer_file": "answer",
        "json_schema_file": "json_schema",
        "reference_trajectory_file": "reference_trajectory",
        "required_facts_file": "required_facts",
    }
    for file_key, target_key in mappings.items():
        if file_key not in expected:
            continue
        path = base / str(expected[file_key])
        text = path.read_text(encoding="utf-8")
        if target_key in {"json_schema", "reference_trajectory", "required_facts"}:
            import json

            resolved[target_key] = json.loads(text)
        else:
            resolved[target_key] = text.strip()
    return resolved
