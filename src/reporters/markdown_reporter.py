from __future__ import annotations

from pathlib import Path

from reporters.json_reporter import summarize
from schemas import AgentRun, EvalCase, EvalResult


def write_markdown_report(path: str | Path, cases: list[EvalCase], runs: list[AgentRun], results: list[EvalResult]) -> None:
    summary = summarize(cases, runs, results)
    lines = [
        "# AgentEval Report",
        "",
        "## Summary",
        "",
        f"- Cases: {summary['cases']}",
        f"- Evaluation results: {summary['results']}",
        f"- Failures: {summary['failures']}",
        f"- Pass rate: {summary['pass_rate']:.2%}",
        f"- Average score: {summary['avg_score']:.2f}",
        f"- Latency p50/p95: {summary['latency_ms']['p50']:.0f}ms / {summary['latency_ms']['p95']:.0f}ms",
        f"- Tokens: input={summary['usage']['input_tokens']}, output={summary['usage']['output_tokens']}, total_input={summary['usage']['total_input_tokens']}, cache_read={summary['usage']['cache_read_input_tokens']}, cache_hit_rate={summary['usage']['cache_hit_rate']:.2%}",
        f"- Tool calls: total={summary['tool_calls']['total']}, failed={summary['tool_calls']['failed']}",
        f"- Run errors: {summary['errors']['total']}",
        f"- Environment sessions: {summary.get('environment', {}).get('sessions', 0)}, files changed: created={summary.get('environment', {}).get('created_files', 0)}, modified={summary.get('environment', {}).get('modified_files', 0)}, deleted={summary.get('environment', {}).get('deleted_files', 0)}, protected violations={summary.get('environment', {}).get('protected_path_violations', 0)}, command failures={summary.get('environment', {}).get('command_failures', 0)}/{summary.get('environment', {}).get('commands', 0)}, query failures={summary.get('environment', {}).get('query_failures', 0)}/{summary.get('environment', {}).get('queries', 0)}, HTTP failures={summary.get('environment', {}).get('http_failures', 0)}/{summary.get('environment', {}).get('http_checks', 0)}, browser failures={summary.get('environment', {}).get('browser_failures', 0)}/{summary.get('environment', {}).get('browser_checks', 0)}, browser screenshots={summary.get('environment', {}).get('browser_screenshots', 0)}",
        "",
        "## By Evaluator",
        "",
        "| Evaluator | Results | Pass rate | Avg score |",
        "| --- | ---: | ---: | ---: |",
    ]
    for evaluator, evaluator_summary in summary["by_evaluator"].items():
        lines.append(f"| {evaluator} | {evaluator_summary['results']} | {evaluator_summary['pass_rate']:.2%} | {evaluator_summary['avg_score']:.2f} |")

    lines.extend([
        "",
        "## By Tag",
        "",
        "| Tag | Results | Pass rate | Avg score |",
        "| --- | ---: | ---: | ---: |",
    ])
    for tag, tag_summary in summary["by_tag"].items():
        lines.append(f"| {tag} | {tag_summary['results']} | {tag_summary['pass_rate']:.2%} | {tag_summary['avg_score']:.2f} |")

    lines.extend([
        "",
        "## By Capability",
        "",
        "| Capability | Results | Pass rate | Avg score |",
        "| --- | ---: | ---: | ---: |",
    ])
    for capability, capability_summary in summary.get("by_capability", {}).items():
        lines.append(f"| {capability} | {capability_summary['results']} | {capability_summary['pass_rate']:.2%} | {capability_summary['avg_score']:.2f} |")

    lines.extend([
        "",
        "## By Risk Level",
        "",
        "| Risk level | Results | Pass rate | Avg score |",
        "| --- | ---: | ---: | ---: |",
    ])
    for risk_level, risk_summary in summary.get("by_risk_level", {}).items():
        lines.append(f"| {risk_level} | {risk_summary['results']} | {risk_summary['pass_rate']:.2%} | {risk_summary['avg_score']:.2f} |")

    lines.extend(["", "## Errors", ""])
    if not summary["errors"]["by_case"]:
        lines.append("No run errors.")
    else:
        for case_id, errors in summary["errors"]["by_case"].items():
            lines.append(f"- `{case_id}`: {'; '.join(errors)}")

    lines.extend(["", "## Failures", ""])
    run_by_key = {(run.case_id, run.repeat_index): run for run in runs}
    failures = [result for result in results if not result.passed]
    if not failures:
        lines.append("No evaluation failures.")
    else:
        for result in failures:
            lines.extend([
                f"### {result.case_id} / {result.evaluator}",
                "",
                f"- Score: {result.score:.2f}",
                f"- Reason: {result.failure_reason or 'N/A'}",
                "",
            ])
            env = run_by_key.get((result.case_id, result.repeat_index), AgentRun(case_id=result.case_id)).artifacts.get("environment") if run_by_key else None
            if env:
                diff = env.get("diff", {})
                commands = env.get("commands", [])
                failed_commands = [command for command in commands if command.get("timed_out") or command.get("exit_code") is None or command.get("exit_code") != 0]
                failed_queries = [query for query in env.get("database", []) if query.get("error")]
                failed_http = [check for check in env.get("http", []) if check.get("error") or check.get("status_code") is None]
                failed_browser = [check for check in env.get("browser", []) if check.get("error") or check.get("status") == "error"]
                lines.extend([
                    "Environment diff:",
                    f"- Created: {', '.join((diff.get('created') or [])[:10]) or 'None'}",
                    f"- Modified: {', '.join((diff.get('modified') or [])[:10]) or 'None'}",
                    f"- Deleted: {', '.join((diff.get('deleted') or [])[:10]) or 'None'}",
                    f"- Protected violations: {', '.join((diff.get('protected_path_violations') or [])[:10]) or 'None'}",
                    f"- Failed commands: {', '.join(command.get('command', '') for command in failed_commands[:5]) or 'None'}",
                    f"- Failed queries: {', '.join(query.get('query', '') for query in failed_queries[:5]) or 'None'}",
                    f"- Failed HTTP checks: {', '.join(check.get('url', '') for check in failed_http[:5]) or 'None'}",
                    f"- Failed browser checks: {', '.join(check.get('url', '') or check.get('selector', '') for check in failed_browser[:5]) or 'None'}",
                    "",
                ])

    Path(path).write_text("\n".join(lines) + "\n", encoding="utf-8")
