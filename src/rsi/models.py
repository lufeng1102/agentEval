from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any

import yaml

SEVERITY_RANK = {"low": 1, "medium": 2, "high": 3, "critical": 4}
STATUS_RANK = {"accepted": 0, "canary": 1, "needs_human_review": 2, "rejected": 3, "rollback_recommended": 4}


def load_artifact(path: str | Path) -> dict[str, Any]:
    file_path = Path(path)
    text = file_path.read_text(encoding="utf-8")
    if file_path.suffix.lower() in {".yaml", ".yml"}:
        data = yaml.safe_load(text) or {}
    else:
        data = json.loads(text)
    if not isinstance(data, dict):
        raise ValueError(f"artifact must contain an object: {path}")
    return data


def load_rsi_policy(path: str | Path | None, section: str | None = None) -> dict[str, Any]:
    if path is None:
        return {}
    payload = load_artifact(path)
    policy = payload.get("rsi_governance", payload)
    if section and isinstance(policy, dict):
        return policy.get(section, policy.get(section.replace("_", "-"), policy.get("safety_envelope", policy)))
    return policy


def evidence(component: str, message: str, *, severity: str = "medium", source: str | None = None, item: str | None = None, details: dict[str, Any] | None = None) -> dict[str, Any]:
    payload: dict[str, Any] = {"component": component, "severity": risk_level(severity), "message": message}
    if source:
        payload["source"] = source
    if item:
        payload["item"] = item
    if details:
        payload["details"] = details
    return payload


def max_risk_level(values: list[str]) -> str:
    if not values:
        return "low"
    return max((risk_level(value) for value in values), key=lambda value: SEVERITY_RANK.get(value, 0))


def gate_result(name: str, status: str, reason: str, *, risk: str = "low", source: str | None = None) -> dict[str, Any]:
    result = {"name": name, "status": status, "risk_level": risk_level(risk), "reason": reason}
    if source:
        result["source"] = source
    return result


def combine_status(left: str, right: str) -> str:
    return left if STATUS_RANK.get(left, 0) >= STATUS_RANK.get(right, 0) else right


def load_report(run_dir: str | Path) -> dict[str, Any]:
    return json.loads((Path(run_dir) / "report.json").read_text(encoding="utf-8"))


def summary(run_dir: str | Path) -> dict[str, Any]:
    return load_report(run_dir).get("summary", {})


def pass_rate(run_dir: str | Path) -> float:
    return float(summary(run_dir).get("pass_rate", 0) or 0)


def report_counts(run_dir: str | Path, report: dict[str, Any] | None = None) -> dict[str, Any]:
    report = report or load_report(run_dir)
    results = report.get("results", []) or []
    total = len(results)
    passed = sum(1 for item in results if item.get("passed"))
    return {"total": total, "passed": passed, "failed": max(0, total - passed), "pass_rate": passed / total if total else float((report.get("summary", {}) or {}).get("pass_rate", 0) or 0)}


def generalization_confidence(known: dict[str, Any], holdout: dict[str, Any], gap: float) -> str:
    n1 = int(known.get("total", 0) or 0)
    n2 = int(holdout.get("total", 0) or 0)
    if min(n1, n2) < 5:
        return "low"
    p1 = float(known.get("pass_rate", 0) or 0)
    p2 = float(holdout.get("pass_rate", 0) or 0)
    stderr = math.sqrt((p1 * (1 - p1) / n1) + (p2 * (1 - p2) / n2)) if n1 and n2 else 1
    if abs(gap) > 2 * stderr:
        return "high"
    return "medium"


def avg_score(run_dir: str | Path) -> float:
    return float(summary(run_dir).get("avg_score", 0) or 0)


def total_tokens(run_dir: str | Path) -> int:
    usage = summary(run_dir).get("usage", {}) or {}
    return int(usage.get("total_input_tokens", 0) or 0) + int(usage.get("output_tokens", 0) or 0)


def risk_level(score_or_severity: int | str) -> str:
    if isinstance(score_or_severity, str):
        return score_or_severity if score_or_severity in SEVERITY_RANK else "low"
    if score_or_severity >= 80:
        return "critical"
    if score_or_severity >= 60:
        return "high"
    if score_or_severity >= 30:
        return "medium"
    return "low"


def write_json(path: str | Path, report: dict[str, Any]) -> None:
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")


def write_markdown(path: str | Path, title: str, report: dict[str, Any]) -> None:
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    lines = [f"# {title}", ""]
    lines.extend(_markdown_obj(report))
    output.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _markdown_obj(value: Any, indent: int = 0) -> list[str]:
    prefix = "  " * indent
    if isinstance(value, dict):
        lines = []
        for key, item in value.items():
            if isinstance(item, (dict, list)):
                lines.append(f"{prefix}- {key}:")
                lines.extend(_markdown_obj(item, indent + 1))
            else:
                lines.append(f"{prefix}- {key}: {item}")
        return lines or [f"{prefix}- None"]
    if isinstance(value, list):
        lines = []
        for item in value:
            if isinstance(item, (dict, list)):
                lines.append(f"{prefix}-")
                lines.extend(_markdown_obj(item, indent + 1))
            else:
                lines.append(f"{prefix}- {item}")
        return lines or [f"{prefix}- None"]
    return [f"{prefix}- {value}"]


def contains_any(text: str, needles: list[str]) -> bool:
    lowered = text.lower()
    return any(needle.lower() in lowered for needle in needles)


def modification_components(modification: dict[str, Any]) -> list[str]:
    return [str(item) for item in modification.get("modified_components", []) or []]


def modification_actions(modification: dict[str, Any]) -> list[str]:
    actions = modification.get("actions", []) or []
    return [str(item.get("type") if isinstance(item, dict) else item) for item in actions]
