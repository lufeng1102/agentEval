from __future__ import annotations

import asyncio
import json
from pathlib import Path

import typer

from agents.static_adapter import StaticAgentAdapter
from config import AppConfig, load_config, load_dataset
from compare import compare_runs, write_compare_markdown
from evaluators import build_evaluator
from manifest import build_manifest, write_manifest
from reporters import summarize, write_html_report, write_html_report_from_json, write_json_report, write_markdown_report
from runners import EvalExecutor

app = typer.Typer(help="Run Claude/LLM agent evaluations.")


@app.callback()
def main() -> None:
    """AgentEval command line interface."""


@app.command()
def run(
    dataset: Path = typer.Option(..., "--dataset", "-d", help="Path to YAML evaluation dataset."),
    config: Path = typer.Option(..., "--config", "-c", help="Path to YAML run config."),
    out: Path = typer.Option(Path("runs/latest"), "--out", "-o", help="Output directory."),
    min_pass_rate: float | None = typer.Option(None, "--min-pass-rate", help="Fail when overall pass rate is below this threshold."),
    min_score: float | None = typer.Option(None, "--min-score", help="Fail when average score is below this threshold."),
    fail_on_error: bool = typer.Option(False, "--fail-on-error/--no-fail-on-error", help="Fail when any agent run records errors."),
    repeats: int | None = typer.Option(None, "--repeats", help="Override runner.repeats for stability testing."),
) -> None:
    """Run a dataset through an agent and configured evaluators."""
    app_config = load_config(config)
    if repeats is not None:
        app_config.runner.repeats = repeats
    eval_dataset = load_dataset(dataset)
    asyncio.run(_run_async(eval_dataset.cases, app_config, out, min_pass_rate, min_score, fail_on_error, dataset, config))


async def _run_async(
    cases,
    config: AppConfig,
    out: Path,
    min_pass_rate: float | None = None,
    min_score: float | None = None,
    fail_on_error: bool = False,
    dataset_path: Path | None = None,
    config_path: Path | None = None,
) -> None:
    agent = _build_agent(config)
    evaluators = [build_evaluator(item) for item in config.evaluators]
    executor = EvalExecutor(agent=agent, evaluators=evaluators, config=config)
    runs, results = await executor.run(cases, out)
    write_manifest(out / "manifest.json", build_manifest(dataset_path, config_path, config))

    if "json" in config.report.formats:
        write_json_report(out / "report.json", cases, runs, results)
    if "markdown" in config.report.formats:
        write_markdown_report(out / "report.md", cases, runs, results)
    if "html" in config.report.formats:
        write_html_report(out / "report.html", cases, runs, results)

    summary = summarize(cases, runs, results)
    typer.echo(
        f"Completed {len(cases)} cases, pass_rate={summary['pass_rate']:.2%}, "
        f"avg_score={summary['avg_score']:.2f}, failures={summary['failures']}, "
        f"cache_hit_rate={summary['usage']['cache_hit_rate']:.2%}. Reports: {out}"
    )

    failures: list[str] = []
    if min_pass_rate is not None and summary["pass_rate"] < min_pass_rate:
        failures.append(f"pass rate {summary['pass_rate']:.2%} is below minimum {min_pass_rate:.2%}")
    if min_score is not None and summary["avg_score"] < min_score:
        failures.append(f"average score {summary['avg_score']:.2f} is below minimum {min_score:.2f}")
    if fail_on_error and summary["errors"]["total"]:
        failures.append(f"{summary['errors']['total']} run errors recorded")

    if failures:
        for failure in failures:
            typer.echo(f"Threshold failed: {failure}", err=True)
        raise typer.Exit(code=1)


@app.command()
def html(
    report: Path = typer.Option(..., "--report", "-r", help="Path to AgentEval report.json."),
    out: Path | None = typer.Option(None, "--out", "-o", help="Output HTML path. Defaults to report.json sibling report.html."),
) -> None:
    """Convert an existing report.json into an HTML report."""
    output_path = out or report.with_name("report.html")
    try:
        payload = json.loads(report.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            raise typer.BadParameter("report JSON must contain an object")
        write_html_report_from_json(output_path, payload)
    except json.JSONDecodeError as exc:
        raise typer.BadParameter(f"invalid JSON report: {exc}") from exc
    typer.echo(f"Wrote HTML report: {output_path}")


@app.command()
def compare(
    baseline: Path = typer.Option(..., "--baseline", help="Baseline run directory containing report.json."),
    candidate: Path = typer.Option(..., "--candidate", help="Candidate run directory containing report.json."),
    out: Path = typer.Option(Path("runs/compare.md"), "--out", help="Markdown compare report path."),
    max_pass_rate_drop: float | None = typer.Option(None, "--max-pass-rate-drop", help="Fail when pass-rate drop exceeds this value."),
    max_avg_score_drop: float | None = typer.Option(None, "--max-avg-score-drop", help="Fail when avg-score drop exceeds this value."),
    fail_on_new_failures: bool = typer.Option(False, "--fail-on-new-failures/--no-fail-on-new-failures", help="Fail when candidate has newly failed case/evaluator pairs."),
) -> None:
    """Compare two AgentEval run directories."""
    comparison = compare_runs(baseline, candidate)
    out.parent.mkdir(parents=True, exist_ok=True)
    write_compare_markdown(out, comparison)
    delta = comparison["delta"]
    typer.echo(
        f"Compared runs: pass_rate_delta={delta['pass_rate']:.2%}, "
        f"avg_score_delta={delta['avg_score']:.2f}, newly_failed={len(comparison['newly_failed'])}. Report: {out}"
    )

    failures: list[str] = []
    if max_pass_rate_drop is not None and delta["pass_rate"] < -max_pass_rate_drop:
        failures.append(f"pass-rate drop {-delta['pass_rate']:.2%} exceeds max {max_pass_rate_drop:.2%}")
    if max_avg_score_drop is not None and delta["avg_score"] < -max_avg_score_drop:
        failures.append(f"avg-score drop {-delta['avg_score']:.2f} exceeds max {max_avg_score_drop:.2f}")
    if fail_on_new_failures and comparison["newly_failed"]:
        failures.append(f"newly failed results: {comparison['newly_failed']}")
    if failures:
        for failure in failures:
            typer.echo(f"Compare threshold failed: {failure}", err=True)
        raise typer.Exit(code=1)
def _discover_configs(paths: list[Path]) -> list[Path]:
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


@app.command()
def matrix(
    dataset: Path = typer.Option(..., "--dataset", "-d", help="Path to YAML evaluation dataset."),
    config: list[Path] = typer.Option(..., "--config", "-c", help="Config file, directory, or glob. Can be repeated."),
    out: Path = typer.Option(Path("runs/matrix"), "--out", help="Output matrix directory."),
) -> None:
    """Run one dataset against multiple configs and compare them."""
    configs = _discover_configs(config)
    if not configs:
        raise typer.BadParameter("no config files found")
    summary = asyncio.run(_run_matrix(dataset, configs, out))
    typer.echo(f"Completed matrix with {len(summary['runs'])} runs. Report: {out / 'matrix.md'}")


async def _run_matrix(dataset: Path, configs: list[Path], out: Path) -> dict:
    from compare import compare_runs, write_compare_markdown

    out.mkdir(parents=True, exist_ok=True)
    dataset_obj = load_dataset(dataset)
    runs: list[dict] = []
    for config_path in configs:
        app_config = load_config(config_path)
        run_dir = out / config_path.stem
        await _run_async(dataset_obj.cases, app_config, run_dir, dataset_path=dataset, config_path=config_path)
        runs.append({"name": config_path.stem, "config": str(config_path), "run_dir": str(run_dir)})

    comparisons: list[dict] = []
    if runs:
        baseline_dir = Path(runs[0]["run_dir"])
        for run_info in runs[1:]:
            comparison = compare_runs(baseline_dir, run_info["run_dir"])
            compare_path = out / f"compare-{runs[0]['name']}-vs-{run_info['name']}.md"
            write_compare_markdown(compare_path, comparison)
            comparisons.append({"baseline": runs[0]["name"], "candidate": run_info["name"], "report": str(compare_path), "delta": comparison["delta"]})
    summary = {"dataset": str(dataset), "runs": runs, "comparisons": comparisons}
    _write_matrix_markdown(out / "matrix.md", summary)
    return summary


def _write_matrix_markdown(path: Path, summary: dict) -> None:
    lines = ["# AgentEval Matrix Report", "", f"- Dataset: `{summary['dataset']}`", "", "## Runs", "", "| Name | Config | Run dir |", "| --- | --- | --- |"]
    for run_info in summary["runs"]:
        lines.append(f"| {run_info['name']} | `{run_info['config']}` | `{run_info['run_dir']}` |")
    lines.extend(["", "## Comparisons", "", "| Baseline | Candidate | Pass-rate delta | Avg-score delta | Report |", "| --- | --- | ---: | ---: | --- |"])
    for comparison in summary["comparisons"]:
        delta = comparison["delta"]
        lines.append(f"| {comparison['baseline']} | {comparison['candidate']} | {delta['pass_rate']:.2%} | {delta['avg_score']:.2f} | `{comparison['report']}` |")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _build_agent(config: AppConfig):
    if config.agent.provider == "static":
        return StaticAgentAdapter(
            config.agent.static_response or "",
            tool_calls=config.agent.static_tool_calls,
            latency_ms=config.agent.static_latency_ms,
            artifacts=config.agent.static_artifacts,
        )
    if config.agent.provider == "anthropic":
        from agents.claude_adapter import ClaudeAgentAdapter

        return ClaudeAgentAdapter(config.agent)
    raise typer.BadParameter(f"unknown agent provider: {config.agent.provider}")


if __name__ == "__main__":
    app()
