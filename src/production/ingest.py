from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from production.models import ProductionEvent
from production.summary import summarize_production
from runners.trace import read_jsonl


def load_production_events(path: str | Path) -> list[ProductionEvent]:
    payloads = _load_payloads(path, "events")
    return [ProductionEvent.model_validate(_normalize_event(item)) for item in payloads]


def ingest_production_events(path: str | Path) -> dict[str, Any]:
    events = load_production_events(path)
    return {
        "source": str(path),
        "summary": summarize_production(events),
        "events": [event.model_dump(mode="json") for event in events],
    }


def _load_payloads(path: str | Path, key: str) -> list[dict[str, Any]]:
    file_path = Path(path)
    if file_path.suffix == ".jsonl":
        return read_jsonl(file_path)
    data = json.loads(file_path.read_text(encoding="utf-8"))
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        values = data.get(key, data.get("records", []))
        if isinstance(values, list):
            return values
    raise ValueError(f"unsupported production input format: {path}")


def _normalize_event(item: dict[str, Any]) -> dict[str, Any]:
    data = dict(item)
    if not data.get("event_id"):
        data["event_id"] = _stable_event_id(data)
    if "input" not in data:
        data["input"] = data.get("case_id") or _input_from_messages(data.get("messages") or []) or "production event"
    data.setdefault("final_output", data.get("output") or "")
    data.setdefault("messages", [])
    data.setdefault("tool_calls", [])
    data.setdefault("outcome", {})
    data.setdefault("usage", {})
    data.setdefault("errors", [])
    data.setdefault("tags", [])
    data.setdefault("metadata", {})
    if data.get("case_id") and "case_id" not in data["metadata"]:
        data["metadata"]["case_id"] = data.get("case_id")
    return data


def _input_from_messages(messages: list[dict[str, Any]]) -> str | None:
    for message in messages:
        if message.get("role") == "user" and message.get("content"):
            return str(message.get("content"))
    return None


def _stable_event_id(data: dict[str, Any]) -> str:
    payload = json.dumps({"session_id": data.get("session_id"), "input": data.get("input"), "timestamp": data.get("timestamp"), "output": data.get("final_output") or data.get("output")}, ensure_ascii=False, sort_keys=True)
    return "prod_" + hashlib.sha1(payload.encode("utf-8")).hexdigest()[:16]
