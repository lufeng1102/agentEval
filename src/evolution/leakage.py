from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from config import load_config, load_dataset
from evolution.artifacts import load_run_artifacts

SECRET_KEYS = {"answer", "required_facts", "reference", "reference_trajectory", "tool_outputs", "final_state"}
LEAK_PATTERNS = ["hidden", "gold", "answer_key", "solution", "reference"]


def analyze_leakage(dataset_path: str | Path, config_path: str | Path | None = None, run_path: str | Path | None = None) -> dict[str, Any]:
    dataset = load_dataset(dataset_path)
    dataset_metadata = dataset.metadata or {}
    config = load_config(config_path) if config_path else None
    issues: list[dict[str, Any]] = []
    for case in dataset.cases:
        case_data = case.model_dump(mode="json")
        issues.extend(_case_leakage_issues(case_data, dataset_metadata))
    if config is not None:
        issues.extend(_config_leakage_issues(config.model_dump(mode="json")))
    if run_path is not None:
        issues.extend(_run_leakage_issues(run_path))
    return {
        "dataset": str(dataset_path),
        "config": str(config_path) if config_path else None,
        "run": str(run_path) if run_path else None,
        "summary": {
            "issues": len(issues),
            "critical": sum(1 for item in issues if item["severity"] == "critical"),
            "high": sum(1 for item in issues if item["severity"] == "high"),
            "medium": sum(1 for item in issues if item["severity"] == "medium"),
            "low": sum(1 for item in issues if item["severity"] == "low"),
        },
        "issues": issues,
        "recommendations": _recommendations(issues),
    }


def write_leakage_json(path: str | Path, report: dict[str, Any]) -> None:
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")


def write_leakage_markdown(path: str | Path, report: dict[str, Any]) -> None:
    summary = report.get("summary", {}) or {}
    lines = [
        "# AgentEval Leakage / Anti-Cheat Report",
        "",
        f"- Dataset: `{report.get('dataset')}`",
        f"- Config: `{report.get('config')}`",
        f"- Run: `{report.get('run')}`",
        f"- Issues: {summary.get('issues', 0)} (critical={summary.get('critical', 0)}, high={summary.get('high', 0)}, medium={summary.get('medium', 0)}, low={summary.get('low', 0)})",
        "",
        "## Recommendations",
        "",
    ]
    lines.extend([f"- {item}" for item in report.get("recommendations", [])] or ["- None"])
    lines.extend(["", "## Issues", "", "| Severity | Category | Case | Title | Evidence |", "| --- | --- | --- | --- | --- |"])
    for issue in report.get("issues", []) or []:
        lines.append(f"| {issue.get('severity')} | `{issue.get('category')}` | `{issue.get('case_id') or ''}` | {issue.get('title')} | {json.dumps(issue.get('evidence') or {}, ensure_ascii=False).replace('|', '/')} |")
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _case_leakage_issues(case: dict[str, Any], dataset_metadata: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    issues = []
    case_id = str(case.get("id"))
    input_text = _stringify(case.get("input"))
    expected = case.get("expected") or {}
    reference = case.get("reference") or (case.get("metadata") or {}).get("reference") or {}
    for key, value in expected.items():
        if key in SECRET_KEYS and _value_exposed(value, input_text):
            issues.append(_issue("high", "answer_exposure", case_id, "Expected answer appears in case input", {"expected_key": key}, "Move hidden answers out of user-visible input or make the task explicitly open-book."))
    if reference and _value_exposed(reference, input_text):
        issues.append(_issue("high", "reference_exposure", case_id, "Reference solution appears in case input", {}, "Keep reference solutions separate from prompts visible to the agent."))
    metadata = case.get("metadata") or {}
    if _suite_type(case, dataset_metadata or {}) == "holdout" and not metadata.get("holdout") and "holdout" not in set(case.get("tags") or []):
        issues.append(_issue("medium", "holdout", case_id, "Holdout case lacks explicit holdout marker", {}, "Add metadata.holdout=true or a holdout tag."))
    scenario = case.get("scenario") or {}
    for tool in scenario.get("tools", []) or []:
        output = tool.get("output") or tool.get("outputs") or tool.get("responses")
        if output and _value_exposed(expected, _stringify(output)):
            issues.append(_issue("medium", "tool_leakage", case_id, "Mock tool output may expose expected answer", {"tool": tool.get("name")}, "Ensure tools reveal only information available in production."))
    return issues


def _config_leakage_issues(config: dict[str, Any]) -> list[dict[str, Any]]:
    issues = []
    env = config.get("environment") or {}
    for key in ["include_patterns", "protected_paths"]:
        for value in env.get(key, []) or []:
            if any(pattern in str(value).lower() for pattern in LEAK_PATTERNS):
                issues.append(_issue("medium", "environment_leakage", None, "Environment pattern references sensitive eval artifacts", {"field": key, "value": value}, "Keep answer keys, hidden tests, and reference files outside agent-visible workspaces."))
    if env.get("reset_between_trials") is False:
        issues.append(_issue("high", "cross_trial_contamination", None, "Environment does not reset between trials", {}, "Enable reset_between_trials to avoid shared-state leakage."))
    return issues


def _run_leakage_issues(run_path: str | Path) -> list[dict[str, Any]]:
    issues = []
    try:
        artifacts = load_run_artifacts(run_path)
    except FileNotFoundError:
        return [_issue("medium", "run", None, "Run artifacts are missing", {"run": str(run_path)}, "Provide a run directory with report.json/traces.jsonl for leakage checks.")]
    for run in artifacts.traces:
        case_id = str(run.get("case_id"))
        env = (run.get("artifacts") or {}).get("environment") or {}
        protected = ((env.get("diff") or {}).get("protected_path_violations") or []) if isinstance(env, dict) else []
        if protected:
            issues.append(_issue("critical", "protected_path", case_id, "Run touched protected paths", {"paths": protected}, "Block access to protected paths and inspect the trial transcript."))
        for call in run.get("tool_calls", []) or []:
            payload = json.dumps(call, ensure_ascii=False, sort_keys=True)
            if any(pattern in payload.lower() for pattern in ["answer_key", "hidden_test", "reference_solution"]):
                issues.append(_issue("high", "tool_leakage", case_id, "Tool call references sensitive eval artifact", {"tool": call.get("name")}, "Remove sensitive eval artifacts from tool-accessible paths or outputs."))
    return issues


def _value_exposed(value: Any, text: str) -> bool:
    haystack = text.lower()
    for token in _tokens(value):
        if len(token) >= 4 and token.lower() in haystack:
            return True
    return False


def _tokens(value: Any) -> list[str]:
    if isinstance(value, str):
        return [value]
    if isinstance(value, dict):
        tokens: list[str] = []
        for item in value.values():
            tokens.extend(_tokens(item))
        return tokens
    if isinstance(value, list):
        tokens = []
        for item in value:
            tokens.extend(_tokens(item))
        return tokens
    return [str(value)] if value is not None else []


def _stringify(value: Any) -> str:
    return value if isinstance(value, str) else json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)


def _suite_type(case: dict[str, Any], dataset_metadata: dict[str, Any] | None = None) -> str:
    metadata = case.get("metadata") or {}
    dataset_metadata = dataset_metadata or {}
    return str(metadata.get("suite_type") or dataset_metadata.get("suite_type") or "").lower()


def _issue(severity: str, category: str, case_id: str | None, title: str, evidence: dict[str, Any], recommendation: str) -> dict[str, Any]:
    raw = f"{category}_{case_id or 'suite'}_{title}"
    safe = re.sub(r"[^a-zA-Z0-9]+", "_", raw).strip("_").lower()
    return {"id": f"leak_{safe[:100]}", "severity": severity, "category": category, "case_id": case_id, "title": title, "evidence": evidence, "recommendation": recommendation}


def _recommendations(issues: list[dict[str, Any]]) -> list[str]:
    categories = {issue.get("category") for issue in issues}
    recs = []
    if "answer_exposure" in categories or "reference_exposure" in categories:
        recs.append("Separate hidden expected answers and reference solutions from user-visible prompts.")
    if "tool_leakage" in categories:
        recs.append("Review mock tools and tool outputs for answer-key or hidden-test leakage.")
    if "cross_trial_contamination" in categories or "protected_path" in categories:
        recs.append("Strengthen environment isolation and protected path policies before using results as release gates.")
    if "holdout" in categories:
        recs.append("Mark holdout cases explicitly and keep them out of prompt-tuning workflows.")
    return recs or ["No obvious leakage or anti-cheat issues detected."]
