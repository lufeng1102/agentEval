from __future__ import annotations

from dataclasses import dataclass, field
from html import escape
from pathlib import Path
from typing import Any

from reporters.json_reporter import summarize
from schemas import AgentRun, EvalCase, EvalResult


@dataclass(frozen=True)
class _CaseDisplay:
    id: str
    name: str | None = None
    tags: list[str] = field(default_factory=list)


def write_html_report(path: str | Path, cases: list[EvalCase], runs: list[AgentRun], results: list[EvalResult]) -> None:
    display_cases = [_CaseDisplay(id=case.id, name=case.name, tags=case.tags) for case in cases]
    _write_html(path, display_cases, runs, results, summarize(cases, runs, results))


def write_html_report_from_json(path: str | Path, payload: dict[str, Any]) -> None:
    """Render an HTML report from an existing report.json payload."""
    runs = [AgentRun.model_validate(item) for item in payload.get("runs", [])]
    results = [EvalResult.model_validate(item) for item in payload.get("results", [])]
    summary = payload.get("summary") or _summarize_without_cases(runs, results)
    cases = _cases_from_payload(payload, runs, results)
    _write_html(path, cases, runs, results, summary)


def _write_html(path: str | Path, cases: list[_CaseDisplay], runs: list[AgentRun], results: list[EvalResult], summary: dict[str, Any]) -> None:
    run_by_case = {run.case_id: run for run in runs}
    results_by_case: dict[str, list[EvalResult]] = {}
    for result in results:
        results_by_case.setdefault(result.case_id, []).append(result)

    pass_rate = float(summary.get("pass_rate", 0) or 0)
    avg_score = float(summary.get("avg_score", 0) or 0)
    failures = int(summary.get("failures", 0) or 0)
    error_count = int(summary.get("errors", {}).get("total", 0) or 0)
    status = "Passing" if failures == 0 and error_count == 0 else "Needs attention"
    status_cls = "good" if failures == 0 and error_count == 0 else "bad"

    html = [
        "<!doctype html>",
        "<html><head><meta charset='utf-8'><meta name='viewport' content='width=device-width, initial-scale=1'>",
        "<title>AgentEval Report</title>",
        f"<style>{_stylesheet()}</style>",
        "</head><body>",
        "<main class='shell'>",
        "<section class='hero'>",
        "<div>",
        "<p class='eyebrow'>AgentEval</p>",
        "<h1>Evaluation Report</h1>",
        "<p class='subtitle'>Visual summary of agent quality, failures, latency, usage, and per-case evaluator results.</p>",
        "</div>",
        f"<div class='status {status_cls}'><span></span>{escape(status)}</div>",
        "</section>",
        "<section class='cards'>",
        _card("Cases", summary.get("cases", len(cases)), "Total dataset cases"),
        _card("Pass rate", f"{pass_rate:.2%}", _meter(pass_rate)),
        _card("Avg score", f"{avg_score:.2f}", _meter(avg_score)),
        _card("Failures", failures, "Failed evaluator results"),
        _card("Run errors", error_count, "Adapter or infrastructure errors"),
        _card("Cache hit", f"{summary.get('usage', {}).get('cache_hit_rate', 0):.2%}", "Prompt cache read ratio"),
        "</section>",
        "<section class='grid two'>",
        _panel("By Evaluator", _summary_table(summary.get("by_evaluator", {}), "Evaluator")),
        _panel("By Tag", _summary_table(summary.get("by_tag", {}), "Tag")),
        "</section>",
        "<section class='grid two'>",
        _panel("Run Errors", _errors(summary.get("errors", {}).get("by_case", {}))),
        _panel("Evaluation Failures", _failures(results)),
        "</section>",
        "<section class='panel'>",
        "<div class='panel-head'><h2>Cases</h2><p>Expand each case to inspect final output and evaluator details.</p></div>",
        "<div class='case-list'>",
    ]

    for case in cases:
        run = run_by_case.get(case.id)
        case_results = results_by_case.get(case.id, [])
        case_failed = any(not result.passed for result in case_results) or bool(run and run.errors)
        badge_cls = "bad" if case_failed else "good"
        badge_text = "Failed" if case_failed else "Passed"
        title = f"{case.id} {case.name or ''}".strip()
        tags = "".join(f"<span class='tag'>{escape(tag)}</span>" for tag in case.tags)
        html.append("<details class='case-card'>")
        html.append(
            f"<summary><div><strong>{escape(title)}</strong><div class='tags'>{tags}</div></div>"
            f"<span class='badge {badge_cls}'>{badge_text}</span></summary>"
        )
        html.append("<div class='case-body'>")
        if run:
            html.append("<div class='meta-row'>")
            html.append(f"<span>Latency <strong>{run.latency_ms:.0f}ms</strong></span>")
            html.append(f"<span>Tool calls <strong>{len(run.tool_calls)}</strong></span>")
            html.append(f"<span>Output tokens <strong>{run.usage.output_tokens}</strong></span>")
            html.append("</div>")
            if run.errors:
                html.append(_notice("Run errors", "; ".join(run.errors), "bad"))
            html.append(f"<h3>Final output</h3><pre>{escape(run.final_output or '<empty>')}</pre>")
            if run.tool_calls:
                html.append("<h3>Tool calls</h3>")
                html.append(_tool_calls(run.tool_calls))
        html.append(_result_table(case_results))
        html.append("</div></details>")

    html.extend(["</div>", "</section>", "</main>", "</body></html>"])
    output_path = Path(path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text("\n".join(html), encoding="utf-8")


def _cases_from_payload(payload: dict[str, Any], runs: list[AgentRun], results: list[EvalResult]) -> list[_CaseDisplay]:
    case_payloads = payload.get("cases")
    if isinstance(case_payloads, list):
        cases = []
        for item in case_payloads:
            if isinstance(item, dict) and item.get("id"):
                tags = item.get("tags") if isinstance(item.get("tags"), list) else []
                cases.append(_CaseDisplay(id=str(item["id"]), name=item.get("name"), tags=[str(tag) for tag in tags]))
        if cases:
            return cases

    ordered_ids: list[str] = []
    seen: set[str] = set()
    for case_id in [run.case_id for run in runs] + [result.case_id for result in results]:
        if case_id not in seen:
            seen.add(case_id)
            ordered_ids.append(case_id)
    return [_CaseDisplay(id=case_id) for case_id in ordered_ids]


def _summarize_without_cases(runs: list[AgentRun], results: list[EvalResult]) -> dict[str, Any]:
    placeholder_cases = [EvalCase(id=case_id, input="<unknown>") for case_id in {run.case_id for run in runs} | {result.case_id for result in results}]
    return summarize(placeholder_cases, runs, results)


def _card(title: str, value: object, detail: str) -> str:
    return f"<article class='card'><p>{escape(title)}</p><strong>{escape(str(value))}</strong><div class='card-detail'>{detail}</div></article>"


def _panel(title: str, body: str) -> str:
    return f"<section class='panel'><div class='panel-head'><h2>{escape(title)}</h2></div>{body}</section>"


def _meter(value: float) -> str:
    pct = max(0, min(100, value * 100))
    return f"<div class='meter'><span style='width:{pct:.2f}%'></span></div>"


def _summary_table(groups: dict, label: str) -> str:
    rows = [f"<div class='table-wrap'><table><tr><th>{escape(label)}</th><th>Results</th><th>Pass rate</th><th>Avg score</th></tr>"]
    if not groups:
        rows.append("<tr><td colspan='4' class='muted'>None</td></tr>")
    for key, item in groups.items():
        pass_rate = float(item.get("pass_rate", 0) or 0)
        rows.append(
            f"<tr><td><code>{escape(str(key))}</code></td><td>{item.get('results', 0)}</td>"
            f"<td>{pass_rate:.2%}{_meter(pass_rate)}</td><td>{float(item.get('avg_score', 0) or 0):.2f}</td></tr>"
        )
    rows.append("</table></div>")
    return "\n".join(rows)


def _errors(errors_by_case: dict[str, list[str]]) -> str:
    if not errors_by_case:
        return _notice("No run errors", "All agent runs completed without recorded runtime errors.", "good")
    items = ["<ul class='issue-list'>"]
    for case_id, errors in errors_by_case.items():
        items.append(f"<li><code>{escape(case_id)}</code><span>{escape('; '.join(errors))}</span></li>")
    items.append("</ul>")
    return "\n".join(items)


def _failures(results: list[EvalResult]) -> str:
    failures = [result for result in results if not result.passed]
    if not failures:
        return _notice("No evaluation failures", "Every evaluator result passed.", "good")
    rows = ["<div class='table-wrap'><table><tr><th>Case</th><th>Evaluator</th><th>Score</th><th>Reason</th></tr>"]
    for result in failures:
        rows.append(
            f"<tr><td><code>{escape(result.case_id)}</code></td><td>{escape(result.evaluator)}</td>"
            f"<td>{result.score:.2f}</td><td>{escape(result.failure_reason or '')}</td></tr>"
        )
    rows.append("</table></div>")
    return "\n".join(rows)


def _result_table(results: list[EvalResult]) -> str:
    rows = ["<h3>Evaluator results</h3><div class='table-wrap'><table><tr><th>Evaluator</th><th>Status</th><th>Score</th><th>Reason</th></tr>"]
    if not results:
        rows.append("<tr><td colspan='4' class='muted'>No evaluator results.</td></tr>")
    for result in results:
        cls = "good" if result.passed else "bad"
        text = "Passed" if result.passed else "Failed"
        rows.append(
            f"<tr><td>{escape(result.evaluator)}</td><td><span class='badge {cls}'>{text}</span></td>"
            f"<td>{result.score:.2f}</td><td>{escape(result.failure_reason or '')}</td></tr>"
        )
    rows.append("</table></div>")
    return "\n".join(rows)


def _tool_calls(tool_calls: list[Any]) -> str:
    rows = ["<div class='table-wrap'><table><tr><th>Name</th><th>Input</th><th>Output</th><th>Error</th></tr>"]
    for call in tool_calls:
        rows.append(
            f"<tr><td><code>{escape(call.name)}</code></td><td><pre>{escape(str(call.input))}</pre></td>"
            f"<td><pre>{escape(str(call.output))}</pre></td><td>{escape(call.error or '')}</td></tr>"
        )
    rows.append("</table></div>")
    return "\n".join(rows)


def _notice(title: str, message: str, tone: str) -> str:
    return f"<div class='notice {tone}'><strong>{escape(title)}</strong><span>{escape(message)}</span></div>"


def _stylesheet() -> str:
    return """
:root{color-scheme:light;--bg:#f5f7fb;--panel:#ffffff;--panel-soft:#f8fafc;--text:#162033;--muted:#667085;--line:#e4e7ec;--brand:#635bff;--brand2:#12b5cb;--good:#067647;--good-bg:#ecfdf3;--bad:#b42318;--bad-bg:#fef3f2;--shadow:0 18px 45px rgba(16,24,40,.10)}
*{box-sizing:border-box}body{margin:0;background:radial-gradient(circle at top left,rgba(99,91,255,.18),transparent 32rem),linear-gradient(180deg,#fbfcff 0%,var(--bg) 28rem);color:var(--text);font-family:Inter,-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif}.shell{max-width:1180px;margin:0 auto;padding:2rem}.hero{display:flex;align-items:flex-start;justify-content:space-between;gap:1.5rem;padding:2rem;border:1px solid rgba(99,91,255,.16);border-radius:28px;background:linear-gradient(135deg,rgba(255,255,255,.94),rgba(244,247,255,.88));box-shadow:var(--shadow)}.eyebrow{margin:0 0 .35rem;color:var(--brand);font-weight:800;letter-spacing:.14em;text-transform:uppercase;font-size:.78rem}h1{font-size:clamp(2rem,4vw,3.5rem);line-height:1;margin:.1rem 0 .75rem}.subtitle{max-width:720px;margin:0;color:var(--muted);font-size:1.05rem}.status,.badge{display:inline-flex;align-items:center;gap:.45rem;border-radius:999px;padding:.42rem .72rem;font-weight:700;font-size:.82rem;white-space:nowrap}.status{box-shadow:inset 0 0 0 1px rgba(0,0,0,.04)}.status span{width:.55rem;height:.55rem;border-radius:50%;background:currentColor}.good{background:var(--good-bg);color:var(--good)}.bad{background:var(--bad-bg);color:var(--bad)}.cards{display:grid;grid-template-columns:repeat(6,minmax(0,1fr));gap:1rem;margin:1.25rem 0}.card{background:var(--panel);border:1px solid var(--line);border-radius:20px;padding:1rem;box-shadow:0 8px 24px rgba(16,24,40,.06)}.card p{margin:0;color:var(--muted);font-size:.86rem}.card strong{display:block;margin:.35rem 0;font-size:1.75rem;letter-spacing:-.03em}.card-detail{min-height:1rem;color:var(--muted);font-size:.8rem}.grid{display:grid;gap:1rem;margin:1rem 0}.grid.two{grid-template-columns:repeat(2,minmax(0,1fr))}.panel{background:rgba(255,255,255,.92);border:1px solid var(--line);border-radius:22px;padding:1.1rem;box-shadow:0 8px 26px rgba(16,24,40,.05)}.panel-head{display:flex;align-items:flex-end;justify-content:space-between;gap:1rem;margin-bottom:.8rem}.panel h2{margin:0;font-size:1.15rem}.panel p{margin:.25rem 0 0;color:var(--muted)}.table-wrap{overflow:auto;border:1px solid var(--line);border-radius:16px;background:#fff}table{border-collapse:collapse;width:100%;font-size:.92rem}th,td{padding:.75rem .85rem;text-align:left;border-bottom:1px solid var(--line);vertical-align:top}th{background:var(--panel-soft);color:#344054;font-size:.76rem;text-transform:uppercase;letter-spacing:.05em}tr:last-child td{border-bottom:0}code{background:#eef2ff;color:#3538cd;border-radius:6px;padding:.12rem .35rem}pre{white-space:pre-wrap;word-break:break-word;background:#0f172a;color:#e2e8f0;padding:.85rem;border-radius:14px;line-height:1.45;overflow:auto}.meter{height:.45rem;margin-top:.35rem;background:#eef2f6;border-radius:999px;overflow:hidden}.meter span{display:block;height:100%;border-radius:999px;background:linear-gradient(90deg,var(--brand),var(--brand2))}.issue-list{margin:0;padding:0;list-style:none}.issue-list li{display:flex;gap:.75rem;padding:.7rem 0;border-bottom:1px solid var(--line)}.issue-list li:last-child{border-bottom:0}.notice{display:flex;flex-direction:column;gap:.25rem;border-radius:16px;padding:1rem}.notice span{color:inherit;opacity:.82}.case-list{display:flex;flex-direction:column;gap:.75rem}.case-card{border:1px solid var(--line);border-radius:18px;background:#fff;overflow:hidden}.case-card summary{cursor:pointer;display:flex;align-items:center;justify-content:space-between;gap:1rem;padding:1rem 1.1rem;list-style:none}.case-card summary::-webkit-details-marker{display:none}.case-card[open] summary{border-bottom:1px solid var(--line);background:var(--panel-soft)}.case-body{padding:1rem}.meta-row{display:flex;flex-wrap:wrap;gap:.6rem;margin-bottom:1rem}.meta-row span{background:var(--panel-soft);border:1px solid var(--line);border-radius:999px;padding:.45rem .7rem;color:var(--muted)}h3{margin:1rem 0 .5rem;font-size:1rem}.tags{display:flex;gap:.35rem;flex-wrap:wrap;margin-top:.35rem}.tag{background:#f2f4f7;color:#475467;border-radius:999px;padding:.18rem .5rem;font-size:.75rem}.muted{color:var(--muted)}@media (max-width:980px){.cards{grid-template-columns:repeat(3,minmax(0,1fr))}.grid.two{grid-template-columns:1fr}.hero{flex-direction:column}}@media (max-width:640px){.shell{padding:1rem}.cards{grid-template-columns:repeat(2,minmax(0,1fr))}.card strong{font-size:1.35rem}.case-card summary{align-items:flex-start;flex-direction:column}.meta-row{flex-direction:column}.meta-row span{border-radius:12px}}
""".strip()
