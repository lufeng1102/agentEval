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
from evolution.artifacts import load_run_artifacts
from environments.analysis import analyze_environment_independence, clean_environment_workspaces, write_environment_analysis_json, write_environment_analysis_markdown, write_environment_cleanup_json, write_environment_cleanup_markdown
from evolution.decisions import make_decision, write_decision_json, write_decision_markdown
from evolution.diagnosis import diagnose_run_pair, write_diagnosis_json, write_diagnosis_markdown
from evolution.failures import cluster_failures, write_failure_clusters_json, write_failure_clusters_markdown
from evolution.experiment import ExperimentRunSpec, load_experiment_spec, write_experiment_markdown
from evolution.flaky import analyze_flaky, write_flaky_json, write_flaky_markdown
from evolution.impact import analyze_impact, write_impact_json, write_impact_markdown
from evolution.judge import apply_judge_overrides, build_judge_context, load_judge_config, merge_judge_diagnosis, run_judge_diagnosis, should_run_judge
from evolution.leaderboard import build_leaderboard, write_leaderboard_json, write_leaderboard_markdown
from evolution.pr_summary import build_pr_summary, write_pr_summary_markdown
from evolution.regression_status import mark_regression, summarize_regressions, update_regression_status, write_regression_status_json, write_regression_status_markdown
from evolution.regressions import append_regression_dataset, generate_regression_dataset, write_regression_dataset
from manifest import build_manifest, write_manifest
from promotion import evaluate_promotion, load_promotion_policy, write_promotion_json, write_promotion_markdown
from reporters import summarize, write_html_report, write_html_report_from_json, write_json_report, write_markdown_report
from runners import EvalExecutor
from rsi.action_risk import analyze_action_risk, write_action_json, write_action_markdown
from rsi.decision_explainer import explain_rsi_decision, write_rsi_decision_json, write_rsi_decision_markdown
from rsi.diff_risk import classify_diff_risk, write_diff_risk_json, write_diff_risk_markdown
from rsi.integrity import analyze_eval_integrity, write_integrity_json, write_integrity_markdown
from rsi.anti_gaming import analyze_anti_gaming, write_anti_gaming_json, write_anti_gaming_markdown
from rsi.attribution import analyze_attribution, write_attribution_json, write_attribution_markdown
from rsi.envelope import check_envelope, write_envelope_json, write_envelope_markdown
from rsi.evolution_loop import analyze_evolution_loop, write_loop_json, write_loop_markdown
from rsi.frontier import analyze_frontier, write_frontier_json, write_frontier_markdown
from rsi.holdout import analyze_holdout_suite, write_holdout_json, write_holdout_markdown
from rsi.memory import review_memory, write_memory_json, write_memory_markdown
from rsi.redteam import run_rsi_redteam, write_redteam_json, write_redteam_markdown
from rsi.self_modification import review_self_modification, write_self_mod_json, write_self_mod_markdown

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


@app.command("env-validate")
def env_validate(
    dataset: Path = typer.Option(..., "--dataset", "-d", help="Path to YAML evaluation dataset."),
    config: Path = typer.Option(..., "--config", "-c", help="Path to YAML run config."),
) -> None:
    """Validate environment harness config and case expectations without running agents."""
    eval_dataset = load_dataset(dataset)
    app_config = load_config(config)
    errors = _validate_environment_config(eval_dataset.cases, app_config)
    if errors:
        for error in errors:
            typer.echo(f"Environment validation error: {error}", err=True)
        raise typer.Exit(code=1)
    typer.echo(f"Environment validation passed: type={app_config.environment.type}, cases={len(eval_dataset.cases)}")


@app.command("env-independence-check")
def env_independence_check(
    run: Path = typer.Option(..., "--run", help="Run directory containing environment.jsonl."),
    out: Path = typer.Option(Path("runs/env-independence.md"), "--out", "-o"),
    formats: list[str] | None = typer.Option(None, "--format"),
) -> None:
    """Check that environment sessions are isolated and complete."""
    report = analyze_environment_independence(run)
    paths = _write_report_outputs(out, report, formats or ["markdown"], write_environment_analysis_markdown, write_environment_analysis_json)
    typer.echo(f"Environment independence passed={report['passed']}, sessions={report['sessions']}. Reports: {', '.join(str(path) for path in paths)}")
    if not report["passed"]:
        raise typer.Exit(code=1)


@app.command("env-clean")
def env_clean(
    run: Path = typer.Option(..., "--run", help="Run directory containing envs/ workspaces."),
    keep_failures: bool = typer.Option(False, "--keep-failures/--no-keep-failures", help="Keep workspaces for failed cases."),
    dry_run: bool = typer.Option(True, "--dry-run/--no-dry-run", help="Only print cleanup plan without deleting."),
    out: Path | None = typer.Option(None, "--out", "-o", help="Optional cleanup report output path."),
    formats: list[str] | None = typer.Option(None, "--format"),
) -> None:
    """Clean environment workspaces while preserving environment.jsonl."""
    report = clean_environment_workspaces(run, keep_failures=keep_failures, dry_run=dry_run)
    if out:
        paths = _write_report_outputs(out, report, formats or ["markdown"], write_environment_cleanup_markdown, write_environment_cleanup_json)
        typer.echo(f"Environment cleanup planned={len(report['planned_delete'])}, deleted={len(report['deleted'])}. Reports: {', '.join(str(path) for path in paths)}")
    else:
        typer.echo(f"Environment cleanup planned={len(report['planned_delete'])}, deleted={len(report['deleted'])}, dry_run={report['dry_run']}")


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


@app.command("diff-risk")
def diff_risk(
    modification: Path = typer.Option(..., "--modification", help="Self-modification manifest JSON/YAML."),
    policy: Path | None = typer.Option(None, "--policy", help="Optional diff risk or safety policy YAML."),
    out: Path = typer.Option(Path("runs/diff-risk.md"), "--out", "-o"),
    formats: list[str] | None = typer.Option(None, "--format"),
    fail_on_review: bool = typer.Option(False, "--fail-on-review/--no-fail-on-review", help="Exit nonzero when diff risk requires human review."),
) -> None:
    """Classify RSI self-modification diff risk."""
    report = classify_diff_risk(modification, policy)
    paths = _write_rsi_outputs(out, report, formats or ["markdown"], write_diff_risk_markdown, write_diff_risk_json)
    typer.echo(f"Diff risk={report['risk_level']}, categories={len(report['risk_categories'])}. Reports: {', '.join(str(path) for path in paths)}")
    if report["risk_level"] == "critical" or (fail_on_review and report["requires_human_review"]):
        raise typer.Exit(code=1)


@app.command("integrity-check")
def integrity_check(
    candidate: Path = typer.Option(..., "--candidate", help="Candidate run directory."),
    baseline: Path | None = typer.Option(None, "--baseline", help="Optional baseline run directory."),
    modification: Path | None = typer.Option(None, "--modification", help="Optional self-modification manifest JSON/YAML."),
    policy: Path | None = typer.Option(None, "--policy", help="Optional eval integrity policy YAML."),
    out: Path = typer.Option(Path("runs/integrity.md"), "--out", "-o"),
    formats: list[str] | None = typer.Option(None, "--format"),
) -> None:
    """Check candidate evaluation artifacts for tampering and completeness."""
    report = analyze_eval_integrity(candidate=candidate, baseline=baseline, modification_path=modification, policy_path=policy)
    paths = _write_rsi_outputs(out, report, formats or ["markdown"], write_integrity_markdown, write_integrity_json)
    typer.echo(f"Eval integrity passed={report['passed']}, risk={report['risk_level']}. Reports: {', '.join(str(path) for path in paths)}")
    if not report["passed"]:
        raise typer.Exit(code=1)


@app.command("rsi-decision")
def rsi_decision(
    baseline: Path = typer.Option(..., "--baseline", help="Baseline run directory containing report.json."),
    candidate: Path = typer.Option(..., "--candidate", help="Candidate run directory containing report.json."),
    policy: Path = typer.Option(..., "--policy", help="YAML promotion policy."),
    integrity_report: Path | None = typer.Option(None, "--integrity-report"),
    diff_risk_report: Path | None = typer.Option(None, "--diff-risk-report"),
    anti_gaming_report: Path | None = typer.Option(None, "--anti-gaming-report"),
    holdout_report: Path | None = typer.Option(None, "--holdout-report"),
    self_mod_report: Path | None = typer.Option(None, "--self-mod-report"),
    out: Path = typer.Option(Path("runs/rsi-decision.md"), "--out", "-o"),
    formats: list[str] | None = typer.Option(None, "--format"),
    fail_on_review: bool = typer.Option(False, "--fail-on-review/--no-fail-on-review", help="Exit nonzero when decision requires human review."),
) -> None:
    """Explain a promotion decision with optional RSI governance reports."""
    report = explain_rsi_decision(
        baseline=baseline,
        candidate=candidate,
        policy=load_promotion_policy(policy),
        integrity_report=integrity_report,
        diff_risk_report=diff_risk_report,
        anti_gaming_report=anti_gaming_report,
        holdout_report=holdout_report,
        self_mod_report=self_mod_report,
    )
    paths = _write_rsi_outputs(out, report, formats or ["markdown"], write_rsi_decision_markdown, write_rsi_decision_json)
    typer.echo(f"RSI decision {report['status']}: risk_score={report['risk_score']}. Reports: {', '.join(str(path) for path in paths)}")
    if report["status"] in {"rejected", "rollback_recommended"} or (fail_on_review and report["status"] == "needs_human_review"):
        raise typer.Exit(code=1)


@app.command("envelope-check")
def envelope_check(
    modification: Path = typer.Option(..., "--modification", help="Self-modification manifest JSON/YAML."),
    policy: Path = typer.Option(..., "--policy", help="RSI safety envelope policy YAML."),
    out: Path = typer.Option(Path("runs/envelope.md"), "--out", "-o"),
    formats: list[str] | None = typer.Option(None, "--format"),
) -> None:
    """Check a self-modification against an RSI safety envelope."""
    report = check_envelope(modification, policy)
    paths = _write_rsi_outputs(out, report, formats or ["markdown"], write_envelope_markdown, write_envelope_json)
    typer.echo(f"Envelope accepted={report['accepted']}. Reports: {', '.join(str(path) for path in paths)}")
    if not report["accepted"]:
        raise typer.Exit(code=1)


@app.command("self-mod-review")
def self_mod_review(
    baseline: Path = typer.Option(..., "--baseline"),
    candidate: Path = typer.Option(..., "--candidate"),
    modification: Path = typer.Option(..., "--modification"),
    policy: Path | None = typer.Option(None, "--policy"),
    out: Path = typer.Option(Path("runs/self-mod-review.md"), "--out", "-o"),
    formats: list[str] | None = typer.Option(None, "--format"),
) -> None:
    """Review whether an RSI self-modification is safe and aligned."""
    report = review_self_modification(baseline, candidate, modification, policy)
    paths = _write_rsi_outputs(out, report, formats or ["markdown"], write_self_mod_markdown, write_self_mod_json)
    typer.echo(f"Self-modification score={report['score']:.2f}, passed={report['passed']}. Reports: {', '.join(str(path) for path in paths)}")


@app.command("anti-gaming")
def anti_gaming(
    baseline: Path = typer.Option(..., "--baseline"),
    candidate: Path = typer.Option(..., "--candidate"),
    known: Path = typer.Option(..., "--known"),
    holdout: Path = typer.Option(..., "--holdout"),
    modification: Path | None = typer.Option(None, "--modification"),
    out: Path = typer.Option(Path("runs/anti-gaming.md"), "--out", "-o"),
    formats: list[str] | None = typer.Option(None, "--format"),
) -> None:
    """Detect reward hacking and evaluator gaming via known-vs-holdout gaps."""
    report = analyze_anti_gaming(baseline, candidate, known, holdout, modification)
    paths = _write_rsi_outputs(out, report, formats or ["markdown"], write_anti_gaming_markdown, write_anti_gaming_json)
    typer.echo(f"Reward hacking risk={report['reward_hacking_risk']}. Reports: {', '.join(str(path) for path in paths)}")


@app.command("holdout")
def holdout(
    suite: Path = typer.Option(..., "--suite"),
    out: Path = typer.Option(Path("runs/holdout.md"), "--out", "-o"),
    formats: list[str] | None = typer.Option(None, "--format"),
) -> None:
    """Analyze known-vs-holdout evaluation results."""
    report = analyze_holdout_suite(suite)
    paths = _write_rsi_outputs(out, report, formats or ["markdown"], write_holdout_markdown, write_holdout_json)
    typer.echo(f"Holdout decision={report['decision']}, gap={report['generalization_gap']:.2%}. Reports: {', '.join(str(path) for path in paths)}")


@app.command("frontier")
def frontier(
    runs: Path = typer.Option(..., "--runs"),
    out: Path = typer.Option(Path("runs/frontier.md"), "--out", "-o"),
    formats: list[str] | None = typer.Option(None, "--format"),
) -> None:
    """Track RSI capability frontier across run reports."""
    report = analyze_frontier(runs)
    paths = _write_rsi_outputs(out, report, formats or ["markdown"], write_frontier_markdown, write_frontier_json)
    typer.echo(f"Frontier capabilities={len(report['capabilities'])}. Reports: {', '.join(str(path) for path in paths)}")


@app.command("attribution")
def attribution(
    spec: Path = typer.Option(..., "--spec"),
    out: Path = typer.Option(Path("runs/attribution.md"), "--out", "-o"),
    formats: list[str] | None = typer.Option(None, "--format"),
) -> None:
    """Attribute improvements to changed RSI components."""
    report = analyze_attribution(spec)
    paths = _write_rsi_outputs(out, report, formats or ["markdown"], write_attribution_markdown, write_attribution_json)
    typer.echo(f"Attribution candidates={len(report['candidates'])}. Reports: {', '.join(str(path) for path in paths)}")


@app.command("evolution-loop")
def evolution_loop(
    spec: Path = typer.Option(..., "--spec"),
    out: Path = typer.Option(Path("runs/evolution-loop.md"), "--out", "-o"),
    formats: list[str] | None = typer.Option(None, "--format"),
) -> None:
    """Evaluate a multi-iteration RSI self-evolution loop."""
    report = analyze_evolution_loop(spec)
    paths = _write_rsi_outputs(out, report, formats or ["markdown"], write_loop_markdown, write_loop_json)
    typer.echo(f"Evolution iterations={report['iterations']}, net_delta={report['net_pass_rate_delta']:.2%}. Reports: {', '.join(str(path) for path in paths)}")


@app.command("memory-review")
def memory_review(
    baseline_memory: Path = typer.Option(..., "--baseline-memory"),
    candidate_memory: Path = typer.Option(..., "--candidate-memory"),
    out: Path = typer.Option(Path("runs/memory-review.md"), "--out", "-o"),
    formats: list[str] | None = typer.Option(None, "--format"),
) -> None:
    """Review RSI memory evolution and pollution risks."""
    report = review_memory(baseline_memory, candidate_memory)
    paths = _write_rsi_outputs(out, report, formats or ["markdown"], write_memory_markdown, write_memory_json)
    typer.echo(f"Memory risk_flags={len(report['risk_flags'])}. Reports: {', '.join(str(path) for path in paths)}")


@app.command("action-risk")
def action_risk(
    actions: Path = typer.Option(..., "--actions"),
    policy: Path | None = typer.Option(None, "--policy"),
    out: Path = typer.Option(Path("runs/action-risk.md"), "--out", "-o"),
    formats: list[str] | None = typer.Option(None, "--format"),
) -> None:
    """Analyze action risk for RSI agent tool/actions."""
    report = analyze_action_risk(actions, policy)
    paths = _write_rsi_outputs(out, report, formats or ["markdown"], write_action_markdown, write_action_json)
    typer.echo(f"Action risk={report['risk_level']}. Reports: {', '.join(str(path) for path in paths)}")


@app.command("rsi-redteam")
def rsi_redteam(
    target: Path = typer.Option(..., "--target"),
    policy: Path = typer.Option(..., "--policy"),
    attacks: Path = typer.Option(..., "--attacks"),
    out: Path = typer.Option(Path("runs/rsi-redteam.md"), "--out", "-o"),
    formats: list[str] | None = typer.Option(None, "--format"),
) -> None:
    """Run static RSI red-team coverage assessment against safety envelope."""
    report = run_rsi_redteam(target, policy, attacks)
    paths = _write_rsi_outputs(out, report, formats or ["markdown"], write_redteam_markdown, write_redteam_json)
    typer.echo(f"RSI redteam risk={report['risk_level']}, vulnerabilities={len(report['vulnerabilities_found'])}. Reports: {', '.join(str(path) for path in paths)}")


@app.command()
def impact(
    baseline: Path = typer.Option(..., "--baseline", help="Baseline run directory containing report.json."),
    candidate: Path = typer.Option(..., "--candidate", help="Candidate run directory containing report.json."),
    out: Path = typer.Option(Path("runs/impact.md"), "--out", "-o", help="Output path for one format, or output stem when multiple formats are requested."),
    formats: list[str] | None = typer.Option(None, "--format", help="Output format: markdown or json. Can be repeated."),
) -> None:
    """Analyze candidate impact against a baseline run."""
    report = analyze_impact(baseline, candidate)
    output_paths = _write_impact_outputs(out, report, formats or ["markdown"])
    typer.echo(f"Impact severity={report['summary']['severity']}, newly_failed={report['summary']['newly_failed']}. Reports: {', '.join(str(path) for path in output_paths)}")


@app.command()
def diagnose(
    baseline: Path = typer.Option(..., "--baseline", help="Baseline run directory containing report.json."),
    candidate: Path = typer.Option(..., "--candidate", help="Candidate run directory containing report.json."),
    out: Path = typer.Option(Path("runs/diagnosis.md"), "--out", "-o", help="Output path for one format, or output stem when multiple formats are requested."),
    formats: list[str] | None = typer.Option(None, "--format", help="Output format: markdown or json. Can be repeated."),
    judge: str = typer.Option("never", "--judge", help="LLM judge mode: never, auto, or always."),
    judge_config: Path | None = typer.Option(None, "--judge-config", help="Optional diagnosis judge YAML config."),
    judge_max_clusters: int | None = typer.Option(None, "--judge-max-clusters", help="Maximum failure clusters sent to the judge."),
    judge_max_cases_per_cluster: int | None = typer.Option(None, "--judge-max-cases-per-cluster", help="Maximum cases per cluster sent to the judge."),
    judge_max_trace_chars: int | None = typer.Option(None, "--judge-max-trace-chars", help="Maximum characters per trace string sent to the judge."),
    judge_timeout_seconds: int | None = typer.Option(None, "--judge-timeout-seconds", help="LLM judge timeout in seconds."),
    judge_cache: bool = typer.Option(True, "--judge-cache/--no-judge-cache", help="Use cached LLM judge reports when possible."),
    judge_strict: bool = typer.Option(False, "--judge-strict/--no-judge-strict", help="Fail diagnose if the LLM judge fails."),
) -> None:
    """Diagnose candidate regressions against a baseline run."""
    report = diagnose_run_pair(baseline, candidate)
    if judge not in {"never", "auto", "always"}:
        raise typer.BadParameter("--judge must be never, auto, or always")
    judge_cfg = apply_judge_overrides(load_judge_config(judge_config), max_clusters=judge_max_clusters, max_cases_per_cluster=judge_max_cases_per_cluster, max_trace_chars=judge_max_trace_chars, cache_enabled=judge_cache, strict=judge_strict, timeout_seconds=judge_timeout_seconds)
    impact_report = analyze_impact(baseline, candidate)
    run_judge, reason = should_run_judge(report, impact_report, judge_cfg, judge)
    if run_judge:
        typer.echo("LLM judge enabled: selected sanitized run artifacts will be sent to Anthropic.", err=True)
        try:
            context = build_judge_context(baseline, candidate, report, impact_report, judge_cfg)
            judge_report = run_judge_diagnosis(context, judge_cfg)
            report = merge_judge_diagnosis(report, judge_report)
        except Exception as exc:
            if judge_cfg.strict:
                raise typer.BadParameter(f"LLM judge failed: {exc}") from exc
            report["judge"] = {"enabled": True, "used": False, "mode": judge, "skipped_reason": f"LLM judge failed: {exc}"}
    else:
        report["judge"] = {"enabled": judge != "never", "used": False, "mode": judge, "skipped_reason": reason}
    output_paths = _write_diagnosis_outputs(out, report, formats or ["markdown"])
    typer.echo(f"Diagnoses: {report['summary']['diagnoses']}, high_confidence={report['summary']['high_confidence']}. Reports: {', '.join(str(path) for path in output_paths)}")


@app.command()
def decide(
    baseline: Path = typer.Option(..., "--baseline", help="Baseline run directory containing report.json."),
    candidate: Path = typer.Option(..., "--candidate", help="Candidate run directory containing report.json."),
    policy: Path = typer.Option(..., "--policy", help="YAML promotion policy."),
    out: Path = typer.Option(Path("runs/decision.md"), "--out", "-o", help="Output path for one format, or output stem when multiple formats are requested."),
    formats: list[str] | None = typer.Option(None, "--format", help="Output format: markdown or json. Can be repeated."),
    fail_on_review: bool = typer.Option(False, "--fail-on-review/--no-fail-on-review", help="Exit nonzero when decision requires human review."),
) -> None:
    """Make an advanced release decision for a candidate run."""
    report = make_decision(baseline, candidate, load_promotion_policy(policy))
    output_paths = _write_decision_outputs(out, report, formats or ["markdown"])
    typer.echo(f"Decision {report['status']}: risk_score={report['risk_score']}. Reports: {', '.join(str(path) for path in output_paths)}")
    if report["status"] in {"rejected", "rollback_recommended"} or (fail_on_review and report["status"] == "needs_human_review"):
        raise typer.Exit(code=1)


@app.command()
def flaky(
    run: Path = typer.Option(..., "--run", help="Run directory containing report.json/results.jsonl."),
    out: Path = typer.Option(Path("runs/flaky.md"), "--out", "-o", help="Output path for one format, or output stem when multiple formats are requested."),
    formats: list[str] | None = typer.Option(None, "--format", help="Output format: markdown or json. Can be repeated."),
) -> None:
    """Analyze repeated evaluator results for flaky behavior."""
    report = analyze_flaky(run)
    output_paths = _write_flaky_outputs(out, report, formats or ["markdown"])
    typer.echo(f"Flaky pairs: {report['summary']['flaky_pairs']}. Reports: {', '.join(str(path) for path in output_paths)}")


@app.command("regression-status")
def regression_status(
    dataset: Path = typer.Option(..., "--dataset", help="Regression dataset YAML path."),
    out: Path | None = typer.Option(None, "--out", "-o", help="Optional output path for one format, or output stem when multiple formats are requested."),
    formats: list[str] | None = typer.Option(None, "--format", help="Output format: markdown or json. Can be repeated."),
) -> None:
    """Summarize regression dataset lifecycle status."""
    report = summarize_regressions(dataset)
    if out:
        output_paths = _write_regression_status_outputs(out, report, formats or ["markdown"])
        typer.echo(f"Regression cases: {report['total']}. Reports: {', '.join(str(path) for path in output_paths)}")
    else:
        typer.echo(f"Regression cases: {report['total']}; by_status={report['by_status']}")


@app.command("regression-update-status")
def regression_update_status(
    dataset: Path = typer.Option(..., "--dataset", help="Regression dataset YAML path."),
    run: Path = typer.Option(..., "--run", help="Run directory containing report.json."),
) -> None:
    """Update regression statuses from a run's results."""
    report = update_regression_status(dataset, run)
    typer.echo(f"Updated {report['updated']} regression cases; by_status={report['by_status']}")


@app.command("regression-mark")
def regression_mark(
    dataset: Path = typer.Option(..., "--dataset", help="Regression dataset YAML path."),
    case: str = typer.Option(..., "--case", help="Regression case ID to mark."),
    status: str = typer.Option(..., "--status", help="New status: active, fixed, flaky, ignored, or needs_review."),
    reason: str | None = typer.Option(None, "--reason", help="Optional reason, used for ignored cases."),
) -> None:
    """Mark a single regression case status."""
    result = mark_regression(dataset, case, status, reason)
    typer.echo(f"Marked {result['case_id']} as {result['status']}")


@app.command("pr-summary")
def pr_summary(
    decision: Path = typer.Option(..., "--decision", help="Path to decision.json."),
    diagnosis: Path | None = typer.Option(None, "--diagnosis", help="Optional path to diagnosis.json."),
    compare: Path | None = typer.Option(None, "--compare", help="Optional path to compare.json."),
    out: Path = typer.Option(..., "--out", "-o", help="Output markdown path."),
) -> None:
    """Write a concise PR-friendly AgentEval decision summary."""
    summary = build_pr_summary(decision, diagnosis, compare)
    write_pr_summary_markdown(out, summary)
    typer.echo(f"Wrote PR summary: {out}")


@app.command()
def failures(
    run: Path | None = typer.Option(None, "--run", help="Run directory containing report.json, traces.jsonl, and manifest.json."),
    report: Path | None = typer.Option(None, "--report", "-r", help="Path to AgentEval report.json. Deprecated; prefer --run."),
    out: Path = typer.Option(Path("runs/failures.md"), "--out", "-o", help="Output path for one format, or output stem when multiple formats are requested."),
    formats: list[str] | None = typer.Option(None, "--format", help="Output format: markdown or json. Can be repeated."),
) -> None:
    """Cluster failed evaluator results by failure type/reason."""
    if run is None and report is None:
        raise typer.BadParameter("either --run or --report is required")
    if run is not None:
        artifacts = load_run_artifacts(run)
        clusters = cluster_failures(artifacts.report, artifacts.traces)
    else:
        payload = json.loads(report.read_text(encoding="utf-8"))
        clusters = cluster_failures(payload, [])
    output_paths = _write_failure_outputs(out, clusters, formats or ["markdown"])
    typer.echo(
        f"Failure clusters: {len(clusters.get('clusters', []))}, "
        f"total_failures={clusters.get('total_failures', 0)}. "
        f"Reports: {', '.join(str(path) for path in output_paths)}"
    )


@app.command()
def regressions(
    run: Path = typer.Option(..., "--run", help="Source run directory containing report.json."),
    out: Path | None = typer.Option(None, "--out", "-o", help="Output YAML regression dataset path."),
    append_to: Path | None = typer.Option(None, "--append-to", help="Append generated regressions to this dataset path."),
    dedupe: bool = typer.Option(False, "--dedupe/--no-dedupe", help="When appending, deduplicate by regression fingerprint and update seen metadata."),
    tag: str | None = typer.Option(None, "--tag", help="Only include failed cases with this tag."),
    evaluator: str | None = typer.Option(None, "--evaluator", help="Only include failures from this evaluator."),
    failure_type: str | None = typer.Option(None, "--failure-type", help="Only include failures with this failure type."),
) -> None:
    """Generate a regression dataset from failed cases in a run."""
    if out is None and append_to is None:
        raise typer.BadParameter("either --out or --append-to is required")
    dataset = generate_regression_dataset(run, tag=tag, evaluator=evaluator, failure_type=failure_type)
    output_path = append_to or out
    if append_to is not None:
        dataset = append_regression_dataset(append_to, dataset, dedupe=dedupe)
    else:
        write_regression_dataset(output_path, dataset)
    typer.echo(f"Generated {len(dataset.get('cases', []))} regression cases: {output_path}")


@app.command()
def experiment(
    spec: Path = typer.Option(..., "--spec", help="Path to an AgentEval evolution experiment YAML spec."),
) -> None:
    """Run or reuse baseline/candidate runs, then compare and promote an experiment."""
    experiment_spec = load_experiment_spec(spec)
    out = experiment_spec.out or Path("runs") / "experiments" / experiment_spec.id
    asyncio.run(_run_experiment_async(experiment_spec, out))
    typer.echo(f"Experiment complete: {out / 'experiment.md'}")


async def _run_experiment_async(experiment_spec, out: Path) -> None:
    out.mkdir(parents=True, exist_ok=True)
    await _run_experiment_side(experiment_spec.baseline, experiment_spec.dataset)
    candidates = experiment_spec.normalized_candidates()
    if len(candidates) == 1 and not experiment_spec.candidates:
        candidate = candidates[0]
        await _run_experiment_side(candidate, experiment_spec.dataset)
        comparison = compare_runs(experiment_spec.baseline.run_dir, candidate.run_dir)
        write_compare_json(out / "compare.json", comparison)
        write_compare_markdown(out / "compare.md", comparison)
        promotion_result = None
        if experiment_spec.promotion_policy:
            promotion_result = evaluate_promotion(experiment_spec.baseline.run_dir, candidate.run_dir, load_promotion_policy(experiment_spec.promotion_policy))
            write_promotion_json(out / "promotion.json", promotion_result)
            write_promotion_markdown(out / "promotion.md", promotion_result)
        write_experiment_markdown(out / "experiment.md", experiment_spec, comparison=comparison, promotion=promotion_result)
        if promotion_result is not None and not promotion_result.accepted:
            for reason in promotion_result.reasons:
                typer.echo(f"Promotion gate failed: {reason}", err=True)
            raise typer.Exit(code=1)
        return

    policy = load_promotion_policy(experiment_spec.promotion_policy) if experiment_spec.promotion_policy else None
    candidate_results: list[dict] = []
    rejected = False
    for index, candidate in enumerate(candidates):
        candidate_id = candidate.id or candidate.run_dir.name or f"candidate-{index + 1}"
        await _run_experiment_side(candidate, experiment_spec.dataset)
        candidate_out = out / "candidates" / candidate_id
        candidate_out.mkdir(parents=True, exist_ok=True)
        comparison = compare_runs(experiment_spec.baseline.run_dir, candidate.run_dir)
        write_compare_json(candidate_out / "compare.json", comparison)
        write_compare_markdown(candidate_out / "compare.md", comparison)
        diagnosis_report = diagnose_run_pair(experiment_spec.baseline.run_dir, candidate.run_dir)
        write_diagnosis_json(candidate_out / "diagnosis.json", diagnosis_report)
        write_diagnosis_markdown(candidate_out / "diagnosis.md", diagnosis_report)
        decision_report = None
        if policy is not None:
            promotion_result = evaluate_promotion(experiment_spec.baseline.run_dir, candidate.run_dir, policy)
            write_promotion_json(candidate_out / "promotion.json", promotion_result)
            write_promotion_markdown(candidate_out / "promotion.md", promotion_result)
            decision_report = make_decision(experiment_spec.baseline.run_dir, candidate.run_dir, policy)
            write_decision_json(candidate_out / "decision.json", decision_report)
            write_decision_markdown(candidate_out / "decision.md", decision_report)
            rejected = rejected or decision_report["status"] in {"rejected", "rollback_recommended"}
        report = load_run_artifacts(candidate.run_dir).report
        candidate_results.append({"id": candidate_id, "run_dir": str(candidate.run_dir), "summary": report.get("summary", {}), "decision": decision_report or {}})
    leaderboard = build_leaderboard(str(experiment_spec.baseline.run_dir), candidate_results)
    write_leaderboard_json(out / "leaderboard.json", leaderboard)
    write_leaderboard_markdown(out / "leaderboard.md", leaderboard)
    write_experiment_markdown(out / "experiment.md", experiment_spec)
    if rejected:
        raise typer.Exit(code=1)


async def _run_experiment_side(run_spec: ExperimentRunSpec, shared_dataset: Path | None) -> None:
    if run_spec.reuse_existing and (run_spec.run_dir / "report.json").exists():
        return
    dataset_path = run_spec.dataset or shared_dataset
    if dataset_path is None or run_spec.config is None:
        raise typer.BadParameter("experiment run requires dataset and config unless reuse_existing report exists")
    app_config = load_config(run_spec.config)
    eval_dataset = load_dataset(dataset_path)
    await _run_async(eval_dataset.cases, app_config, run_spec.run_dir, dataset_path=dataset_path, config_path=run_spec.config)


@app.command()
def promote(
    baseline: Path = typer.Option(..., "--baseline", help="Baseline run directory containing report.json."),
    candidate: Path = typer.Option(..., "--candidate", help="Candidate run directory containing report.json."),
    policy: Path = typer.Option(..., "--policy", help="YAML promotion policy."),
    out: Path = typer.Option(Path("runs/promotion.md"), "--out", "-o", help="Output path for one format, or output stem when multiple formats are requested."),
    formats: list[str] | None = typer.Option(None, "--format", help="Output format: markdown or json. Can be repeated."),
) -> None:
    """Evaluate whether a candidate run should be promoted."""
    result = evaluate_promotion(baseline, candidate, load_promotion_policy(policy))
    output_paths = _write_promotion_outputs(out, result, formats or ["markdown"])
    status = "accepted" if result.accepted else "rejected"
    typer.echo(f"Promotion {status}: reasons={len(result.reasons)}. Reports: {', '.join(str(path) for path in output_paths)}")
    if not result.accepted:
        for reason in result.reasons:
            typer.echo(f"Promotion gate failed: {reason}", err=True)
        raise typer.Exit(code=1)


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
        path = _multi_format_output_path(out, normalized, multiple)
        if normalized == "markdown":
            write_compare_markdown(path, comparison)
        elif normalized == "json":
            write_compare_json(path, comparison)
        else:
            write_compare_html(path, comparison)
        output_paths.append(path)
    return output_paths


def _write_failure_outputs(out: Path, clusters: dict, formats: list[str]) -> list[Path]:
    output_paths: list[Path] = []
    multiple = len(formats) > 1
    for fmt in formats:
        normalized = _normalize_text_format(fmt)
        path = _multi_format_output_path(out, normalized, multiple)
        if normalized == "markdown":
            write_failure_clusters_markdown(path, clusters)
        else:
            write_failure_clusters_json(path, clusters)
        output_paths.append(path)
    return output_paths


def _write_promotion_outputs(out: Path, result, formats: list[str]) -> list[Path]:
    output_paths: list[Path] = []
    multiple = len(formats) > 1
    for fmt in formats:
        normalized = _normalize_text_format(fmt)
        path = _multi_format_output_path(out, normalized, multiple)
        if normalized == "markdown":
            write_promotion_markdown(path, result)
        else:
            write_promotion_json(path, result)
        output_paths.append(path)
    return output_paths


def _write_impact_outputs(out: Path, report: dict, formats: list[str]) -> list[Path]:
    return _write_report_outputs(out, report, formats, write_impact_markdown, write_impact_json)


def _write_diagnosis_outputs(out: Path, report: dict, formats: list[str]) -> list[Path]:
    return _write_report_outputs(out, report, formats, write_diagnosis_markdown, write_diagnosis_json)


def _write_decision_outputs(out: Path, report: dict, formats: list[str]) -> list[Path]:
    return _write_report_outputs(out, report, formats, write_decision_markdown, write_decision_json)


def _write_flaky_outputs(out: Path, report: dict, formats: list[str]) -> list[Path]:
    return _write_report_outputs(out, report, formats, write_flaky_markdown, write_flaky_json)


def _write_regression_status_outputs(out: Path, report: dict, formats: list[str]) -> list[Path]:
    return _write_report_outputs(out, report, formats, write_regression_status_markdown, write_regression_status_json)


def _write_rsi_outputs(out: Path, report: dict, formats: list[str], markdown_writer, json_writer) -> list[Path]:
    return _write_report_outputs(out, report, formats, markdown_writer, json_writer)


def _write_report_outputs(out: Path, report: dict, formats: list[str], markdown_writer, json_writer) -> list[Path]:
    output_paths: list[Path] = []
    multiple = len(formats) > 1
    for fmt in formats:
        normalized = _normalize_text_format(fmt)
        path = _multi_format_output_path(out, normalized, multiple)
        if normalized == "markdown":
            markdown_writer(path, report)
        else:
            json_writer(path, report)
        output_paths.append(path)
    return output_paths


def _normalize_text_format(fmt: str) -> str:
    normalized = fmt.lower()
    if normalized == "md":
        normalized = "markdown"
    if normalized not in {"markdown", "json"}:
        raise typer.BadParameter(f"unsupported output format: {fmt}")
    return normalized


def _multi_format_output_path(out: Path, fmt: str, multiple: bool) -> Path:
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
        if "environment" in selected and "environment" not in expected:
            errors.append(f"case {case.id} uses environment but expected.environment is missing")
        if "tests" in selected and "tests" not in expected:
            errors.append(f"case {case.id} uses tests but expected.tests is missing")
    errors.extend(_validate_environment_config(cases, config))
    return errors


def _validate_environment_config(cases, config: AppConfig) -> list[str]:
    errors: list[str] = []
    env = config.environment
    if env.type not in {"none", "filesystem", "database", "http_api"}:
        errors.append(f"unsupported environment type: {env.type}")
    if env.type != "none":
        if env.command_timeout_seconds <= 0:
            errors.append("environment.command_timeout_seconds must be greater than 0")
        if env.max_command_output_chars < 0:
            errors.append("environment.max_command_output_chars must be greater than or equal to 0")
        if env.retain_workspaces not in {"always", "on_failure", "never"}:
            errors.append("environment.retain_workspaces must be one of: always, on_failure, never")
        for key in ["setup_commands", "test_commands", "teardown_commands"]:
            if not _is_string_list(getattr(env, key)):
                errors.append(f"environment.{key} must be a list of strings")
    if env.type == "filesystem":
        if env.isolation != "copy":
            errors.append("filesystem environment only supports isolation=copy")
        if env.fixture is None:
            errors.append("filesystem environment requires environment.fixture")
        elif not env.fixture.exists() or not env.fixture.is_dir():
            errors.append(f"environment fixture does not exist or is not a directory: {env.fixture}")
    if env.type == "database" and env.fixture is not None and (not env.fixture.exists() or not env.fixture.is_file()):
        errors.append(f"database environment fixture does not exist or is not a file: {env.fixture}")
    for case in cases:
        case_env = case.environment or {}
        case_type = case_env.get("type", env.type)
        if case_type not in {"none", "filesystem", "database", "http_api"}:
            errors.append(f"case {case.id} has unsupported environment type: {case_type}")
        fixture = case_env.get("fixture")
        if fixture is not None:
            fixture_path = Path(fixture)
            if case_type == "filesystem" and (not fixture_path.exists() or not fixture_path.is_dir()):
                errors.append(f"case {case.id} environment fixture does not exist or is not a directory: {fixture}")
            if case_type == "database" and (not fixture_path.exists() or not fixture_path.is_file()):
                errors.append(f"case {case.id} database environment fixture does not exist or is not a file: {fixture}")
        for key in ["setup_commands", "test_commands", "teardown_commands"]:
            if key in case_env and not _is_string_list(case_env[key]):
                errors.append(f"case {case.id} environment.{key} must be a list of strings")
        for key in ["setup_queries", "test_queries", "teardown_queries", "setup_checks", "test_checks", "teardown_checks"]:
            if key in case_env and not isinstance(case_env[key], list):
                errors.append(f"case {case.id} environment.{key} must be a list")
        selected = set(case.evaluators or {item.type for item in config.evaluators})
        if "environment" in selected and "environment" not in case.expected:
            errors.append(f"case {case.id} uses environment but expected.environment is missing")
        expected_env = case.expected.get("environment", {}) if isinstance(case.expected, dict) else {}
        for key in ["required_files", "forbidden_files", "required_modified_files", "forbidden_modified_files", "no_deleted_files", "required_command_success", "forbidden_command_failure"]:
            if key in expected_env and not _is_string_list(expected_env[key]):
                errors.append(f"case {case.id} expected.environment.{key} must be a list of strings")
        for key in ["required_command_stdout", "forbidden_command_stdout"]:
            if key in expected_env and not isinstance(expected_env[key], list):
                errors.append(f"case {case.id} expected.environment.{key} must be a list")
        if "max_command_failures" in expected_env and not isinstance(expected_env["max_command_failures"], int):
            errors.append(f"case {case.id} expected.environment.max_command_failures must be an integer")
        for section, list_keys in {"database": ["required_query_success", "required_rows", "forbidden_rows"], "http": ["required_status", "required_json_paths"]}.items():
            if section in expected_env:
                if not isinstance(expected_env[section], dict):
                    errors.append(f"case {case.id} expected.environment.{section} must be an object")
                    continue
                for key in list_keys:
                    if key in expected_env[section] and not isinstance(expected_env[section][key], list):
                        errors.append(f"case {case.id} expected.environment.{section}.{key} must be a list")
        expected_tests = case.expected.get("tests", {}) if isinstance(case.expected, dict) else {}
        if "tests" in selected:
            if not isinstance(expected_tests, dict):
                errors.append(f"case {case.id} expected.tests must be an object")
            else:
                for key in ["fail_to_pass", "pass_to_pass"]:
                    if key in expected_tests and not isinstance(expected_tests[key], list):
                        errors.append(f"case {case.id} expected.tests.{key} must be a list")
                if "max_test_failures" in expected_tests and not isinstance(expected_tests["max_test_failures"], int):
                    errors.append(f"case {case.id} expected.tests.max_test_failures must be an integer")
    return errors


def _is_string_list(value) -> bool:
    return isinstance(value, list) and all(isinstance(item, str) for item in value)


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
