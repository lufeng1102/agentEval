import json
from pathlib import Path


def write_run(path: Path, pass_rate: float = 1.0, capability: str = "self_modification", difficulty: int = 1, risk_level: str = "low") -> Path:
    path.mkdir(parents=True, exist_ok=True)
    report = {
        "summary": {
            "pass_rate": pass_rate,
            "avg_score": pass_rate,
            "latency_ms": {"p50": 10, "p95": 20},
            "usage": {"total_input_tokens": 10, "output_tokens": 5},
        },
        "cases": [
            {
                "id": "c1",
                "input": "q",
                "metadata": {"capability": capability, "sub_capability": capability, "difficulty": difficulty, "risk_level": risk_level},
            }
        ],
        "results": [{"case_id": "c1", "evaluator": "contains", "passed": pass_rate >= 1.0, "score": pass_rate}],
    }
    (path / "report.json").write_text(json.dumps(report), encoding="utf-8")
    return path


def write_json(path: Path, payload: dict) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path
