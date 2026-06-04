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

    lines.extend(["", "## Errors", ""])
    if not summary["errors"]["by_case"]:
        lines.append("No run errors.")
    else:
        for case_id, errors in summary["errors"]["by_case"].items():
            lines.append(f"- `{case_id}`: {'; '.join(errors)}")

    lines.extend(["", "## Failures", ""])
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

    Path(path).write_text("\n".join(lines) + "\n", encoding="utf-8")
