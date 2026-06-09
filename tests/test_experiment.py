from pathlib import Path

import pytest
import yaml
from pydantic import ValidationError
from typer.testing import CliRunner

from cli import app
from evolution.experiment import load_experiment_spec, write_experiment_markdown
from promotion import PromotionResult


runner = CliRunner()


def test_load_experiment_spec_with_shared_dataset(tmp_path: Path) -> None:
    spec_path = tmp_path / "experiment.yaml"
    spec_path.write_text(
        """
experiment:
  id: support-v2
  dataset: dataset.yaml
  baseline:
    config: baseline.yaml
    run_dir: runs/baseline
  candidate:
    config: candidate.yaml
    run_dir: runs/candidate
  promotion_policy: policy.yaml
  mutation:
    type: prompt_edit
""".strip(),
        encoding="utf-8",
    )

    spec = load_experiment_spec(spec_path)

    assert spec.id == "support-v2"
    assert spec.dataset == Path("dataset.yaml")
    assert spec.baseline.config == Path("baseline.yaml")
    assert spec.candidate.run_dir == Path("runs/candidate")
    assert spec.mutation["type"] == "prompt_edit"


def test_experiment_spec_requires_dataset_and_config_unless_reusing(tmp_path: Path) -> None:
    spec_path = tmp_path / "bad.yaml"
    spec_path.write_text(
        yaml.safe_dump(
            {
                "experiment": {
                    "id": "bad",
                    "baseline": {"run_dir": "runs/base"},
                    "candidate": {"run_dir": "runs/cand", "reuse_existing": True},
                }
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(ValidationError):
        load_experiment_spec(spec_path)


def test_write_experiment_markdown(tmp_path: Path) -> None:
    spec_path = tmp_path / "experiment.yaml"
    spec_path.write_text(
        yaml.safe_dump(
            {
                "experiment": {
                    "id": "support-v2",
                    "dataset": "dataset.yaml",
                    "baseline": {"config": "baseline.yaml", "run_dir": "runs/baseline"},
                    "candidate": {"config": "candidate.yaml", "run_dir": "runs/candidate"},
                }
            }
        ),
        encoding="utf-8",
    )
    spec = load_experiment_spec(spec_path)
    out = tmp_path / "nested" / "experiment.md"

    write_experiment_markdown(
        out,
        spec,
        comparison={"delta": {"pass_rate": 0.1, "avg_score": 0.2}, "newly_failed": [], "newly_passed": ["c1::contains"]},
        promotion=PromotionResult(accepted=True, reasons=[], metrics={}, baseline="b", candidate="c"),
    )

    text = out.read_text(encoding="utf-8")
    assert "AgentEval Evolution Experiment" in text
    assert "Pass-rate delta: 10.00%" in text
    assert "Accepted: True" in text


def test_experiment_cli_runs_static_experiment(tmp_path: Path) -> None:
    dataset = tmp_path / "dataset.yaml"
    dataset.write_text(
        """
cases:
  - id: c1
    input: q
    expected:
      required_facts: [ok]
    evaluators: [contains]
""".strip(),
        encoding="utf-8",
    )
    config = tmp_path / "config.yaml"
    config.write_text(
        """
agent:
  provider: static
  static_response: ok
evaluators:
  - type: contains
report:
  formats: [json, markdown]
""".strip(),
        encoding="utf-8",
    )
    policy = tmp_path / "policy.yaml"
    policy.write_text("promotion:\n  min_pass_rate: 1.0\n", encoding="utf-8")
    spec = tmp_path / "experiment.yaml"
    out = tmp_path / "experiment-out"
    spec.write_text(
        yaml.safe_dump(
            {
                "experiment": {
                    "id": "static-exp",
                    "dataset": str(dataset),
                    "out": str(out),
                    "baseline": {"config": str(config), "run_dir": str(tmp_path / "baseline")},
                    "candidate": {"config": str(config), "run_dir": str(tmp_path / "candidate")},
                    "promotion_policy": str(policy),
                    "mutation": {"type": "test"},
                }
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )

    result = runner.invoke(app, ["experiment", "--spec", str(spec)])

    assert result.exit_code == 0, result.output
    assert (out / "compare.json").exists()
    assert (out / "compare.md").exists()
    assert (out / "promotion.json").exists()
    assert (out / "promotion.md").exists()
    assert "AgentEval Evolution Experiment" in (out / "experiment.md").read_text(encoding="utf-8")


def test_experiment_cli_reuses_existing_runs_without_configs(tmp_path: Path) -> None:
    baseline = tmp_path / "baseline"
    candidate = tmp_path / "candidate"
    for run_dir in [baseline, candidate]:
        run_dir.mkdir()
        (run_dir / "report.json").write_text(
            '{"summary":{"pass_rate":1.0,"avg_score":1.0,"latency_ms":{"p50":1,"p95":1},"usage":{"total_input_tokens":0,"output_tokens":0}},"results":[{"case_id":"c1","evaluator":"contains","passed":true}]}',
            encoding="utf-8",
        )
    spec = tmp_path / "reuse.yaml"
    out = tmp_path / "reuse-out"
    spec.write_text(
        yaml.safe_dump(
            {
                "experiment": {
                    "id": "reuse-exp",
                    "out": str(out),
                    "baseline": {"run_dir": str(baseline), "reuse_existing": True},
                    "candidate": {"run_dir": str(candidate), "reuse_existing": True},
                }
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )

    result = runner.invoke(app, ["experiment", "--spec", str(spec)])

    assert result.exit_code == 0, result.output
    assert (out / "compare.json").exists()
    assert not (out / "promotion.json").exists()


def test_experiment_cli_fails_when_promotion_rejects(tmp_path: Path) -> None:
    dataset = tmp_path / "dataset.yaml"
    dataset.write_text(
        """
cases:
  - id: c1
    input: q
    expected:
      required_facts: [ok]
    evaluators: [contains]
""".strip(),
        encoding="utf-8",
    )
    baseline_config = tmp_path / "baseline.yaml"
    baseline_config.write_text("agent:\n  provider: static\n  static_response: ok\nevaluators:\n  - type: contains\nreport:\n  formats: [json]\n", encoding="utf-8")
    candidate_config = tmp_path / "candidate.yaml"
    candidate_config.write_text("agent:\n  provider: static\n  static_response: bad\nevaluators:\n  - type: contains\nreport:\n  formats: [json]\n", encoding="utf-8")
    policy = tmp_path / "policy.yaml"
    policy.write_text("promotion:\n  min_pass_rate: 1.0\n  fail_on_new_failures: true\n", encoding="utf-8")
    spec = tmp_path / "reject.yaml"
    out = tmp_path / "reject-out"
    spec.write_text(
        yaml.safe_dump(
            {
                "experiment": {
                    "id": "reject-exp",
                    "dataset": str(dataset),
                    "out": str(out),
                    "baseline": {"config": str(baseline_config), "run_dir": str(tmp_path / "baseline-run")},
                    "candidate": {"config": str(candidate_config), "run_dir": str(tmp_path / "candidate-run")},
                    "promotion_policy": str(policy),
                }
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )

    result = runner.invoke(app, ["experiment", "--spec", str(spec)])

    assert result.exit_code == 1
    assert "Promotion gate failed" in result.output
    assert (out / "promotion.json").exists()
    assert (out / "experiment.md").exists()
