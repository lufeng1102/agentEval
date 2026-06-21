from __future__ import annotations

import json
from pathlib import Path


def write_run(run_dir: Path) -> Path:
    run_dir.mkdir(parents=True, exist_ok=True)
    report = {
        "summary": {},
        "cases": [
            {"id": "c_fail", "input": "q1", "expected": {"answer": "ok"}, "tags": ["safety"], "metadata": {"risk_level": "critical", "capability": "support"}},
            {"id": "c_pass", "input": "q2", "expected": {}, "tags": ["general"], "metadata": {"risk_level": "low", "capability": "qa"}},
        ],
        "runs": [],
        "results": [
            {"case_id": "c_fail", "repeat_index": 0, "evaluator": "rubric_judge", "score": 0.2, "passed": False, "failure_type": "safety_under_refusal", "failure_reason": "unsafe", "judgements": [{"score": 0.2}]},
            {"case_id": "c_pass", "repeat_index": 0, "evaluator": "contains", "score": 1.0, "passed": True, "failure_type": None, "failure_reason": None, "judgements": []},
        ],
    }
    traces = [
        {"case_id": "c_fail", "repeat_index": 0, "messages": [{"role": "user", "content": "q1"}, {"role": "assistant", "content": "bad"}], "final_output": "bad", "tool_calls": [{"name": "lookup", "input": {"id": "A100"}, "output": {"status": "blocked"}, "error": None}], "artifacts": {"dynamic": {"stop_reason": "max_turns", "turns": [{"index": 0, "assistant": "bad", "tool_calls": []}], "simulator_turns": [{"type": "llm", "reply": "continue"}], "state_history": [{"turn": 0, "state": {"order": "blocked"}}], "final_state": {"order": "blocked"}}, "environment": {"summary": {"command_failures": 1}, "commands": [{"phase": "test", "command": "pytest", "exit_code": 1}]}}},
        {"case_id": "c_pass", "repeat_index": 0, "messages": [{"role": "user", "content": "q2"}], "final_output": "ok", "tool_calls": [], "artifacts": {}},
    ]
    (run_dir / "report.json").write_text(json.dumps(report), encoding="utf-8")
    (run_dir / "manifest.json").write_text("{}", encoding="utf-8")
    (run_dir / "traces.jsonl").write_text("\n".join(json.dumps(item) for item in traces) + "\n", encoding="utf-8")
    return run_dir
