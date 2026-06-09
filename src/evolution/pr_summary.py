from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def build_pr_summary(decision_path: str | Path, diagnosis_path: str | Path | None = None, compare_path: str | Path | None = None) -> str:
    decision = _load_json(decision_path)
    diagnosis = _load_json(diagnosis_path) if diagnosis_path else {}
    compare = _load_json(compare_path) if compare_path else {}
    lines = [
        f"## AgentEval Decision: {decision.get('status')}",
        "",
        f"- Risk score: {decision.get('risk_score')} / 100",
        f"- Risk level: {decision.get('risk_level')}",
    ]
    if compare:
        delta = compare.get("delta", {})
        lines.extend([f"- Pass-rate delta: {float(delta.get('pass_rate', 0)):.2%}", f"- Newly failed: {len(compare.get('newly_failed', []) or [])}"])
    lines.extend(["", "### Main reasons", ""])
    lines.extend([f"- {item.get('message')}" for item in (decision.get("reasons", []) or [])[:5]] or ["None"])
    lines.extend(["", "### Required actions", ""])
    lines.extend([f"- {action}" for action in (decision.get("required_actions", []) or [])[:5]] or ["None"])
    if diagnosis:
        lines.extend(["", "### Top diagnoses", ""])
        lines.extend([f"- `{item.get('root_cause')}`: {item.get('title')}" for item in (diagnosis.get("diagnoses", []) or [])[:3]] or ["None"])
    lines.extend(["", "### Artifacts", "", f"- Decision: `{decision_path}`"])
    if diagnosis_path:
        lines.append(f"- Diagnosis: `{diagnosis_path}`")
    if compare_path:
        lines.append(f"- Compare: `{compare_path}`")
    return "\n".join(lines) + "\n"


def write_pr_summary_markdown(path: str | Path, summary: str) -> None:
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(summary, encoding="utf-8")


def _load_json(path: str | Path | None) -> dict[str, Any]:
    if path is None:
        return {}
    return json.loads(Path(path).read_text(encoding="utf-8"))
