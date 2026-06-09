from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import json

from runners.trace import read_jsonl


@dataclass
class RunArtifacts:
    run_dir: Path
    report: dict[str, Any]
    traces: list[dict[str, Any]]
    manifest: dict[str, Any]


def load_run_artifacts(run_dir: str | Path, require_report: bool = True) -> RunArtifacts:
    path = Path(run_dir)
    report_path = path / "report.json"
    if report_path.exists():
        report = json.loads(report_path.read_text(encoding="utf-8"))
    elif require_report:
        raise FileNotFoundError(f"report.json not found in {path}")
    else:
        report = {}
    manifest_path = path / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8")) if manifest_path.exists() else {}
    traces = read_jsonl(path / "traces.jsonl")
    return RunArtifacts(run_dir=path, report=report, traces=traces, manifest=manifest)


def version_delta(baseline: RunArtifacts, candidate: RunArtifacts) -> dict[str, dict[str, Any]]:
    base = baseline.manifest.get("agent_version", {}) or {}
    cand = candidate.manifest.get("agent_version", {}) or {}
    keys = sorted(set(base) | set(cand))
    return {key: {"baseline": base.get(key), "candidate": cand.get(key)} for key in keys if base.get(key) != cand.get(key)}
