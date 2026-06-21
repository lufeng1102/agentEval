from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any

from config import AppConfig, load_config, load_dataset
from evaluators import build_evaluator
from runners.trace import read_jsonl
from schemas import AgentRun, ChatMessage, EvalCase, EvalResult, ToolCall, Usage


async def validate_references(dataset_path: str | Path, config_path: str | Path) -> dict[str, Any]:
    """Validate case reference solutions against configured evaluators."""
    dataset = load_dataset(dataset_path)
    config = load_config(config_path)
    evaluators = [build_evaluator(item) for item in config.evaluators]
    configured = {evaluator.name: evaluator for evaluator in evaluators}
    items: list[dict[str, Any]] = []

    for case in dataset.cases:
        reference = _case_reference(case)
        if not reference:
            items.append(
                {
                    "case_id": case.id,
                    "status": "missing",
                    "passed": False,
                    "results": [],
                    "errors": ["reference solution is missing"],
                }
            )
            continue
        try:
            run = _reference_run(case, reference, Path(dataset_path).parent)
        except Exception as exc:  # keep validating the rest of the suite
            items.append(
                {
                    "case_id": case.id,
                    "status": "invalid",
                    "passed": False,
                    "results": [],
                    "errors": [f"{exc.__class__.__name__}: {exc}"],
                }
            )
            continue

        selected = case.evaluators or list(configured)
        results: list[EvalResult] = []
        errors: list[str] = []
        for evaluator_name in selected:
            evaluator = configured.get(evaluator_name)
            if evaluator is None:
                errors.append(f"evaluator is not configured: {evaluator_name}")
                continue
            try:
                results.append(await evaluator.evaluate(case, run))
            except Exception as exc:  # evaluator misconfiguration is a reference validation failure
                errors.append(f"{evaluator_name}: {exc.__class__.__name__}: {exc}")
        passed = not errors and bool(results) and all(result.passed for result in results)
        items.append(
            {
                "case_id": case.id,
                "status": "passed" if passed else "failed",
                "passed": passed,
                "results": [result.model_dump(mode="json") for result in results],
                "errors": errors,
            }
        )

    summary = {
        "cases": len(dataset.cases),
        "with_reference": sum(1 for item in items if item["status"] != "missing"),
        "missing_reference": sum(1 for item in items if item["status"] == "missing"),
        "passed": sum(1 for item in items if item["passed"]),
        "failed": sum(1 for item in items if not item["passed"]),
    }
    return {
        "dataset": str(dataset_path),
        "config": str(config_path),
        "summary": summary,
        "items": items,
    }


def validate_references_sync(dataset_path: str | Path, config_path: str | Path) -> dict[str, Any]:
    return asyncio.run(validate_references(dataset_path, config_path))


def write_reference_validation_json(path: str | Path, report: dict[str, Any]) -> None:
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")


def write_reference_validation_markdown(path: str | Path, report: dict[str, Any]) -> None:
    summary = report.get("summary", {}) or {}
    lines = [
        "# AgentEval Reference Validation",
        "",
        f"- Dataset: `{report.get('dataset')}`",
        f"- Config: `{report.get('config')}`",
        f"- Cases: {summary.get('cases', 0)}",
        f"- With reference: {summary.get('with_reference', 0)}",
        f"- Missing reference: {summary.get('missing_reference', 0)}",
        f"- Passed: {summary.get('passed', 0)}",
        f"- Failed: {summary.get('failed', 0)}",
        "",
        "## Items",
        "",
        "| Case | Status | Passed | Errors |",
        "| --- | --- | --- | --- |",
    ]
    for item in report.get("items", []) or []:
        errors = "; ".join(item.get("errors") or [])
        lines.append(f"| `{item.get('case_id')}` | `{item.get('status')}` | {item.get('passed')} | {errors.replace('|', '/')} |")
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _case_reference(case: EvalCase) -> dict[str, Any]:
    if case.reference:
        return case.reference
    metadata_ref = case.metadata.get("reference") if isinstance(case.metadata, dict) else None
    return dict(metadata_ref) if isinstance(metadata_ref, dict) else {}


def _reference_run(case: EvalCase, reference: dict[str, Any], base_dir: Path) -> AgentRun:
    if reference.get("trace_file"):
        trace_path = Path(reference["trace_file"])
        if not trace_path.is_absolute():
            trace_path = base_dir / trace_path
        if trace_path.suffix == ".jsonl":
            payloads = read_jsonl(trace_path)
            payload = next((item for item in payloads if item.get("case_id") == case.id), payloads[0] if payloads else {})
        else:
            payload = json.loads(trace_path.read_text(encoding="utf-8"))
            if isinstance(payload, list):
                payload = next((item for item in payload if item.get("case_id") == case.id), payload[0] if payload else {})
        return AgentRun.model_validate(payload)

    messages = [ChatMessage.model_validate(item) for item in reference.get("messages", []) or []]
    if not messages:
        messages = _case_messages(case)
    final_output = _coalesced_reference_text(reference)
    if final_output and (not messages or messages[-1].role != "assistant"):
        messages.append(ChatMessage(role="assistant", content=final_output))
    artifacts = dict(reference.get("artifacts") or {})
    if "final_state" in reference and "final_state" not in artifacts:
        artifacts["final_state"] = reference["final_state"]
    if "environment" in reference and "environment" not in artifacts:
        artifacts["environment"] = reference["environment"]
    usage = Usage.model_validate(reference.get("usage") or {})
    return AgentRun(
        case_id=str(reference.get("case_id") or case.id),
        repeat_index=int(reference.get("repeat_index", 0) or 0),
        messages=messages,
        final_output=final_output,
        tool_calls=[ToolCall.model_validate(item) for item in reference.get("tool_calls", []) or []],
        latency_ms=float(reference.get("latency_ms", 0) or 0),
        usage=usage,
        errors=[str(item) for item in reference.get("errors", []) or []],
        raw_response=reference.get("raw_response"),
        artifacts=artifacts,
    )


def _coalesced_reference_text(reference: dict[str, Any]) -> str:
    for key in ["final_output", "output", "answer"]:
        if key in reference:
            return str(reference[key])
    return ""


def _case_messages(case: EvalCase) -> list[ChatMessage]:
    if isinstance(case.input, str):
        return [ChatMessage(role="user", content=case.input)]
    return list(case.input)
