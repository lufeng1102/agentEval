from __future__ import annotations

from pathlib import Path


def discover_configs(paths: list[Path]) -> list[Path]:
    configs: list[Path] = []
    for path in paths:
        if path.is_dir():
            configs.extend(sorted(path.glob("*.yaml")))
            configs.extend(sorted(path.glob("*.yml")))
        elif any(char in str(path) for char in "*?[]"):
            configs.extend(sorted(Path().glob(str(path))))
        else:
            configs.append(path)
    return configs


def write_matrix_markdown(path: Path, summary: dict) -> None:
    lines = ["# AgentEval Matrix Report", "", f"- Dataset: `{summary['dataset']}`", "", "## Runs", "", "| Name | Config | Run dir |", "| --- | --- | --- |"]
    for run in summary["runs"]:
        lines.append(f"| {run['name']} | `{run['config']}` | `{run['run_dir']}` |")
    lines.extend(["", "## Comparisons", "", "| Baseline | Candidate | Pass-rate delta | Avg-score delta | Report |", "| --- | --- | ---: | ---: | --- |"])
    for comparison in summary["comparisons"]:
        delta = comparison["delta"]
        lines.append(f"| {comparison['baseline']} | {comparison['candidate']} | {delta['pass_rate']:.2%} | {delta['avg_score']:.2f} | `{comparison['report']}` |")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
