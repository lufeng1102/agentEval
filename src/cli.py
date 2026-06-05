from __future__ import annotations

import asyncio
import importlib
import json
from pathlib import Path

import typer

from agents.static_adapter import StaticAgentAdapter
from config import AppConfig, load_config, load_dataset
from compare import compare_runs, write_compare_html, write_compare_json, write_compare_markdown
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
    case_ids: list[str] | None = typer.Option(None, "--case", help="Run only matching case ID. Can be repeated."),
    tags: list[str] | None = typer.Option(None, "--tag", help="Run only cases that have this tag. Can be repeated."),
    exclude_tags: list[str] | None = typer.Option(None, "--exclude-tag", help="Skip cases that have this tag. Can be repeated."),
    resume: bool = typer.Option(False, "--resume/--no-resume", help="Reuse existing traces in --out and run only missing case repeats."),
    max_total_tokens: int | None = typer.Option(None, "--max-total-tokens", help="Fail when total input+output tokens exceed this run budget."),
    max_total_cost_usd: float | None = typer.Option(None, "--max-total-cost-usd", help="Fail when estimated run cost exceeds this budget. Requires cost rates."),
) -> None:
    """Run a dataset through an agent and configured evaluators."""
    app_config = load_config(config)
    if repeats is not None:
        app_config.runner.repeats = repeats
    eval_dataset = load_dataset(dataset)
    cases = _filter_cases(eval_dataset.cases, case_ids or [], tags or [], exclude_tags or [])
    asyncio.run(_run_async(cases, app_config, out, min_pass_rate, min_score, fail_on_error, dataset, config, resume, max_total_tokens, max_total_cost_usd))


@app.command()
def validate(
    dataset: Path = typer.Option(..., "--dataset", "-d", help="Path to YAML evaluation dataset."),
    config: Path = typer.Option(..., "--config", "-c", help="Path to YAML run config."),
) -> None:
    """Validate dataset/config compatibility without running agents."""
    eval_dataset = load_dataset(dataset)
    app_config = load_config(config)
    errors = _validate_dataset_config(eval_dataset.cases, app_config)
    if errors:
        for error in errors:
            typer.echo(f"Validation error: {error}", err=True)
        raise typer.Exit(code=1)
    typer.echo(f"Validation passed: {len(eval_dataset.cases)} cases, {len(app_config.evaluators)} evaluators")


async def _run_async(
    cases,
    config: AppConfig,
    out: Path,
    min_pass_rate: float | None = None,
    min_score: float | None = None,
    fail_on_error: bool = False,
    dataset_path: Path | None = None,
    config_path: Path | None = None,
    resume: bool = False,
    max_total_tokens: int | None = None,
    max_total_cost_usd: float | None = None,
) -> None:
    agent = _build_agent(config)
    evaluators = [build_evaluator(item) for item in config.evaluators]
    executor = EvalExecutor(agent=agent, evaluators=evaluators, config=config)
    runs, results = await executor.run(cases, out, resume=resume)
    write_manifest(out / "manifest.json", build_manifest(dataset_path, config_path, config))

    if "json" in config.report.formats:
        write_json_report(out / "report.json", cases, runs, results)
    if "markdown" in config.report.formats:
        write_markdown_report(out / "report.md", cases, runs, results)
    if "html" in config.report.formats:
        write_html_report(out / "report.html", cases, runs, results)

    summary = summarize(cases, runs, results)
    if resume:
        typer.echo(f"Resumed {executor.resumed_runs} existing runs from {out}")
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
    if max_total_tokens is not None:
        actual_tokens = summary["usage"].get("total_input_tokens", 0) + summary["usage"].get("output_tokens", 0)
        if actual_tokens > max_total_tokens:
            failures.append(f"total tokens {actual_tokens} exceeded budget {max_total_tokens}")
    if max_total_cost_usd is not None:
        estimated_cost = _estimated_run_cost(runs, config)
        if estimated_cost > max_total_cost_usd:
            failures.append(f"estimated cost ${estimated_cost:.6f} exceeded budget ${max_total_cost_usd:.6f}")

    if failures:
        for failure in failures:
            typer.echo(f"Threshold failed: {failure}", err=True)
        raise typer.Exit(code=1)


@app.command()
def failures(
    report: Path = typer.Option(..., "--report", "-r", help="Path to AgentEval report.json."),
) -> None:
    """Cluster failed evaluator results by failure type/reason."""
    payload = json.loads(report.read_text(encoding="utf-8"))
    clusters: dict[str, list[str]] = {}
    for result in payload.get("results", []) or []:
        if result.get("passed"):
            continue
        key = result.get("failure_type") or f"{result.get('evaluator')}::{result.get('failure_reason') or 'unknown'}"
        clusters.setdefault(str(key), []).append(f"{result.get('case_id')}::{result.get('evaluator')}")
    typer.echo(f"Failure clusters: {len(clusters)}")
    for key, items in sorted(clusters.items(), key=lambda item: len(item[1]), reverse=True):
        typer.echo(f"- {key}: {len(items)}")
        for item in items[:5]:
            typer.echo(f"  - {item}")


@app.command()
def flakes(
    report: Path = typer.Option(..., "--report", "-r", help="Path to AgentEval report.json."),
) -> None:
    """Show flaky-case stability information from a report.json file."""
    payload = json.loads(report.read_text(encoding="utf-8"))
    stability = payload.get("summary", {}).get("stability", {})
    flaky_cases = stability.get("flaky_cases", []) or []
    typer.echo(f"Flaky cases: {len(flaky_cases)}")
    typer.echo(f"pass_at_1={stability.get('pass_at_1', 0):.2%}, pass_at_k={stability.get('pass_at_k', 0):.2%}, pass_all={stability.get('pass_all', 0):.2%}")
    for case_id in flaky_cases:
        stats = stability.get("cases", {}).get(case_id, {})
        typer.echo(f"- {case_id}: pass_rate={stats.get('pass_rate', 0):.2%}, score_stddev={stats.get('score_stddev', 0):.2f}")


@app.command()
def dashboard(
    runs: Path = typer.Option(..., "--runs", help="Directory containing run subdirectories with report.json files."),
    out: Path = typer.Option(Path("runs/dashboard.html"), "--out", "-o", help="Output dashboard HTML path."),
) -> None:
    """Write a multi-run dashboard from run report.json files."""
    run_infos = _collect_run_reports(runs)
    _write_dashboard_html(out, run_infos)
    typer.echo(f"Wrote dashboard: {out}")


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
    out: Path = typer.Option(Path("runs/compare.md"), "--out", help="Output path for one format, or output stem when multiple formats are requested."),
    formats: list[str] | None = typer.Option(None, "--format", help="Output format: markdown, json, or html. Can be repeated."),
    max_pass_rate_drop: float | None = typer.Option(None, "--max-pass-rate-drop", help="Fail when pass-rate drop exceeds this value."),
    max_avg_score_drop: float | None = typer.Option(None, "--max-avg-score-drop", help="Fail when avg-score drop exceeds this value."),
    fail_on_new_failures: bool = typer.Option(False, "--fail-on-new-failures/--no-fail-on-new-failures", help="Fail when candidate has newly failed case/evaluator pairs."),
) -> None:
    """Compare two AgentEval run directories."""
    comparison = compare_runs(baseline, candidate)
    output_paths = _write_compare_outputs(out, comparison, formats or ["markdown"])
    delta = comparison["delta"]
    typer.echo(
        f"Compared runs: pass_rate_delta={delta['pass_rate']:.2%}, "
        f"avg_score_delta={delta['avg_score']:.2f}, newly_failed={len(comparison['newly_failed'])}. "
        f"Reports: {', '.join(str(path) for path in output_paths)}"
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
def _estimated_run_cost(runs, config: AppConfig) -> float:
    settings = next((item.settings for item in config.evaluators if item.type == "cost"), {})
    input_rate = float(settings.get("input_cost_per_million", 0))
    output_rate = float(settings.get("output_cost_per_million", 0))
    cache_write_rate = float(settings.get("cache_write_cost_per_million", input_rate * 1.25 if input_rate else 0))
    cache_read_rate = float(settings.get("cache_read_cost_per_million", input_rate * 0.1 if input_rate else 0))
    total = 0.0
    for run in runs:
        total += (
            run.usage.input_tokens * input_rate
            + run.usage.output_tokens * output_rate
            + run.usage.cache_creation_input_tokens * cache_write_rate
            + run.usage.cache_read_input_tokens * cache_read_rate
        ) / 1_000_000
    return total


def _collect_run_reports(runs_dir: Path) -> list[dict]:
    reports = []
    for report_path in sorted(runs_dir.glob("*/report.json")):
        payload = json.loads(report_path.read_text(encoding="utf-8"))
        reports.append({"name": report_path.parent.name, "path": str(report_path.parent), "summary": payload.get("summary", {})})
    if not reports:
        raise typer.BadParameter(f"no report.json files found under {runs_dir}")
    return reports


def _write_dashboard_html(path: Path, run_infos: list[dict]) -> None:
    rows = []
    for item in run_infos:
        summary = item["summary"]
        rows.append(
            "<tr>"
            f"<td><code>{item['name']}</code></td>"
            f"<td>{summary.get('pass_rate', 0):.2%}</td>"
            f"<td>{summary.get('avg_score', 0):.2f}</td>"
            f"<td>{summary.get('failures', 0)}</td>"
            f"<td>{summary.get('latency_ms', {}).get('p50', 0):.0f}ms</td>"
            f"<td>{summary.get('usage', {}).get('total_input_tokens', 0) + summary.get('usage', {}).get('output_tokens', 0)}</td>"
            f"<td>{summary.get('errors', {}).get('total', 0)}</td>"
            "</tr>"
        )
    best = max(run_infos, key=lambda item: item["summary"].get("pass_rate", 0))
    html = [
        "<!doctype html><html><head><meta charset='utf-8'><title>AgentEval Runs Dashboard</title>",
        "<style>body{font-family:-apple-system,BlinkMacSystemFont,Segoe UI,sans-serif;margin:2rem;background:#f6f8fa;color:#182230}.card,table{background:white;border:1px solid #e4e7ec;border-radius:16px} .card{padding:1rem;margin:1rem 0}table{border-collapse:collapse;width:100%;overflow:hidden}th,td{padding:.75rem;border-bottom:1px solid #e4e7ec;text-align:left}th{background:#f9fafb}code{background:#eef2ff;padding:.12rem .35rem;border-radius:6px}</style>",
        "</head><body><h1>AgentEval Runs Dashboard</h1>",
        f"<section class='card'><strong>Runs:</strong> {len(run_infos)} &nbsp; <strong>Best pass rate:</strong> {best['name']} ({best['summary'].get('pass_rate', 0):.2%})</section>",
        "<table><tr><th>Run</th><th>Pass rate</th><th>Avg score</th><th>Failures</th><th>Latency p50</th><th>Total tokens</th><th>Errors</th></tr>",
        *rows,
        "</table></body></html>",
    ]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(html), encoding="utf-8")


def _write_compare_outputs(out: Path, comparison: dict, formats: list[str]) -> list[Path]:
    output_paths: list[Path] = []
    multiple = len(formats) > 1
    for fmt in formats:
        normalized = fmt.lower()
        if normalized == "md":
            normalized = "markdown"
        if normalized not in {"markdown", "json", "html"}:
            raise typer.BadParameter(f"unsupported compare format: {fmt}")
        path = _compare_output_path(out, normalized, multiple)
        if normalized == "markdown":
            write_compare_markdown(path, comparison)
        elif normalized == "json":
            write_compare_json(path, comparison)
        else:
            write_compare_html(path, comparison)
        output_paths.append(path)
    return output_paths


def _compare_output_path(out: Path, fmt: str, multiple: bool) -> Path:
    if not multiple:
        return out
    suffix = ".md" if fmt == "markdown" else f".{fmt}"
    return out.with_suffix(suffix)


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
    from compare import compare_runs, write_compare_html, write_compare_json, write_compare_markdown

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


def _filter_cases(cases, case_ids: list[str], tags: list[str], exclude_tags: list[str]):
    selected = list(cases)
    if case_ids:
        requested = set(case_ids)
        selected = [case for case in selected if case.id in requested]
    if tags:
        required_tags = set(tags)
        selected = [case for case in selected if required_tags.intersection(case.tags)]
    if exclude_tags:
        blocked_tags = set(exclude_tags)
        selected = [case for case in selected if not blocked_tags.intersection(case.tags)]
    if not selected:
        raise typer.BadParameter("no cases matched filters")
    return selected


def _validate_dataset_config(cases, config: AppConfig) -> list[str]:
    errors: list[str] = []
    configured = {item.type for item in config.evaluators}
    for case in cases:
        selected = case.evaluators or list(configured)
        for evaluator in selected:
            if evaluator not in configured:
                errors.append(f"case {case.id} references evaluator '{evaluator}' not configured in config.evaluators")
        expected = case.expected
        if "contains" in selected and not expected.get("required_facts"):
            errors.append(f"case {case.id} uses contains but expected.required_facts is missing")
        if "exact_match" in selected and "answer" not in expected:
            errors.append(f"case {case.id} uses exact_match but expected.answer is missing")
        if "regex" in selected and "regex" not in expected:
            errors.append(f"case {case.id} uses regex but expected.regex is missing")
        if "json_schema" in selected and "json_schema" not in expected:
            errors.append(f"case {case.id} uses json_schema but expected.json_schema is missing")
        if "safety" in selected and "should_refuse" not in expected and not expected.get("forbidden_terms"):
            errors.append(f"case {case.id} uses safety but expected.should_refuse or expected.forbidden_terms is missing")
        if "trajectory" in selected and not any(key in expected for key in ["required_tools", "forbidden_tools", "max_tool_calls", "max_latency_ms", "reference_trajectory", "tool_calls", "milestones"]):
            errors.append(f"case {case.id} uses trajectory but no trajectory expectations are configured")
        if "tool_output" in selected and "tool_outputs" not in expected:
            errors.append(f"case {case.id} uses tool_output but expected.tool_outputs is missing")
        if "state" in selected and "final_state" not in expected and "forbidden_state" not in expected:
            errors.append(f"case {case.id} uses state but expected.final_state or expected.forbidden_state is missing")
        if "minefield" in selected and "minefields" not in expected:
            errors.append(f"case {case.id} uses minefield but expected.minefields is missing")
        if "rubric_judge" in selected and not case.rubric:
            errors.append(f"case {case.id} uses rubric_judge but rubric is missing")
    return errors


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
    if config.agent.provider == "claude_code":
        from agents.claude_code_adapter import ClaudeCodeAgentAdapter

        return ClaudeCodeAgentAdapter(config.agent)
    if config.agent.provider in {"import", "plugin"}:
        return _build_imported_agent(config)
    raise typer.BadParameter(f"unknown agent provider: {config.agent.provider}")


def _build_imported_agent(config: AppConfig):
    import_path = config.agent.settings.get("import_path") or config.agent.settings.get("path")
    if not import_path:
        raise typer.BadParameter("import agent requires agent.settings.import_path")
    module_name, _, attr = str(import_path).rpartition(".")
    if not module_name or not attr:
        raise typer.BadParameter(f"invalid agent import path: {import_path}")
    module = importlib.import_module(module_name)
    factory = getattr(module, attr)
    try:
        return factory(config)
    except TypeError:
        return factory()


if __name__ == "__main__":
    app()
