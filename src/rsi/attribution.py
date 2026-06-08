from __future__ import annotations

from pathlib import Path
from typing import Any

from compare import compare_runs
from rsi.models import load_artifact, write_json, write_markdown


def analyze_attribution(spec_path: str | Path) -> dict[str, Any]:
    payload = load_artifact(spec_path)
    spec = payload.get("attribution", payload.get("experiment", payload))
    baseline = spec.get("baseline", {}).get("run_dir") or spec.get("baseline")
    candidates = spec.get("candidates", []) or []
    results = []
    component_effects: dict[str, list[float]] = {}
    for candidate in candidates:
        run_dir = candidate.get("run_dir")
        comparison = compare_runs(baseline, run_dir)
        delta = comparison.get("delta", {})
        components = [str(item) for item in candidate.get("changed_components", []) or []]
        for component in components:
            component_effects.setdefault(component, []).append(float(delta.get("pass_rate", 0) or 0))
        results.append({"id": candidate.get("id") or Path(run_dir).name, "run_dir": run_dir, "changed_components": components, "pass_rate_delta": delta.get("pass_rate", 0), "avg_score_delta": delta.get("avg_score", 0)})
    return {"spec": str(spec_path), "baseline": str(baseline), "candidates": results, "component_attribution": {key: sum(values) / len(values) for key, values in component_effects.items()}}


def write_attribution_json(path: str | Path, report: dict[str, Any]) -> None:
    write_json(path, report)


def write_attribution_markdown(path: str | Path, report: dict[str, Any]) -> None:
    write_markdown(path, "AgentEval RSI Improvement Attribution Report", report)
