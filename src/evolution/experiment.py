from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, Field, model_validator


class ExperimentRunSpec(BaseModel):
    id: str | None = None
    dataset: Path | None = None
    config: Path | None = None
    run_dir: Path
    reuse_existing: bool = False


class ExperimentSpec(BaseModel):
    id: str
    out: Path | None = None
    dataset: Path | None = None
    baseline: ExperimentRunSpec
    candidate: ExperimentRunSpec | None = None
    candidates: list[ExperimentRunSpec] = Field(default_factory=list)
    promotion_policy: Path | None = None
    mutation: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_run_inputs(self) -> "ExperimentSpec":
        candidate_runs = self.normalized_candidates()
        if not candidate_runs:
            raise ValueError("experiment requires candidate or candidates")
        for label, run in {"baseline": self.baseline, **{f"candidate:{_run_id(run, index)}": run for index, run in enumerate(candidate_runs)}}.items():
            dataset = run.dataset or self.dataset
            if not run.reuse_existing and (dataset is None or run.config is None):
                raise ValueError(f"{label} requires dataset and config unless reuse_existing is true")
        return self

    def normalized_candidates(self) -> list[ExperimentRunSpec]:
        if self.candidates:
            return self.candidates
        return [self.candidate] if self.candidate is not None else []

    @property
    def primary_candidate(self) -> ExperimentRunSpec:
        candidates = self.normalized_candidates()
        if not candidates:
            raise ValueError("experiment has no candidate")
        return candidates[0]


def _run_id(run: ExperimentRunSpec, index: int) -> str:
    return run.id or run.run_dir.name or f"candidate-{index + 1}"


def load_experiment_spec(path: str | Path) -> ExperimentSpec:
    payload = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
    if not isinstance(payload, dict):
        raise ValueError(f"experiment spec must contain an object: {path}")
    return ExperimentSpec.model_validate(payload.get("experiment", payload))


def write_experiment_markdown(path: str | Path, spec: ExperimentSpec, comparison: dict[str, Any] | None = None, promotion: Any | None = None) -> None:
    lines = [
        "# AgentEval Evolution Experiment",
        "",
        f"- ID: `{spec.id}`",
        f"- Baseline: `{spec.baseline.run_dir}`",
        f"- Candidate: `{spec.primary_candidate.run_dir}`",
    ]
    if spec.mutation:
        lines.extend(["", "## Mutation", ""])
        for key, value in spec.mutation.items():
            lines.append(f"- {key}: {value}")
    if comparison:
        delta = comparison.get("delta", {})
        lines.extend([
            "",
            "## Compare Summary",
            "",
            f"- Pass-rate delta: {float(delta.get('pass_rate', 0)):.2%}",
            f"- Avg-score delta: {float(delta.get('avg_score', 0)):.2f}",
            f"- Newly failed: {len(comparison.get('newly_failed', []))}",
            f"- Newly passed: {len(comparison.get('newly_passed', []))}",
        ])
    if promotion is not None:
        lines.extend(["", "## Promotion", "", f"- Accepted: {promotion.accepted}", "", "### Reasons", ""])
        lines.extend([f"- {reason}" for reason in promotion.reasons] or ["None"])
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text("\n".join(lines) + "\n", encoding="utf-8")
