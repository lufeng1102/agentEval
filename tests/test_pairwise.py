import json
from pathlib import Path

from evolution.pairwise import PairwiseJudgeConfig, compare_pairwise, run_pairwise_judge, write_pairwise_html, write_pairwise_json, write_pairwise_markdown


def _write_run(path: Path, *, case_id: str = "c1", passed: bool = True, score: float = 1.0, output: str = "ok", tags=None, capability="refund", risk_level="high", latency_ms: float = 100) -> None:
    path.mkdir(parents=True, exist_ok=True)
    report = {
        "summary": {"pass_rate": 1.0 if passed else 0.0, "avg_score": score, "latency_ms": {"p50": latency_ms, "p95": latency_ms}, "usage": {"total_input_tokens": 1, "output_tokens": 1}},
        "cases": [{"id": case_id, "input": "question", "tags": tags or ["support"], "metadata": {"capability": capability, "risk_level": risk_level}}],
        "runs": [{"case_id": case_id, "final_output": output, "latency_ms": latency_ms, "errors": []}],
        "results": [{"case_id": case_id, "evaluator": "contains", "passed": passed, "score": score, "failure_reason": None if passed else "missing"}],
    }
    (path / "report.json").write_text(json.dumps(report), encoding="utf-8")
    (path / "traces.jsonl").write_text(json.dumps({"case_id": case_id, "final_output": output, "latency_ms": latency_ms, "errors": [], "tool_calls": []}) + "\n", encoding="utf-8")
    (path / "manifest.json").write_text(json.dumps({"agent_version": {"version": path.name}}), encoding="utf-8")


def test_pairwise_candidate_wins_when_candidate_passes(tmp_path: Path) -> None:
    baseline = tmp_path / "baseline"
    candidate = tmp_path / "candidate"
    _write_run(baseline, passed=False, score=0.2, output="bad")
    _write_run(candidate, passed=True, score=1.0, output="good")

    report = compare_pairwise(baseline, candidate)

    assert report["summary"]["candidate_wins"] == 1
    assert report["items"][0]["winner"] == "candidate"
    assert report["by_tag"]["support"]["candidate_wins"] == 1
    assert report["by_capability"]["refund"]["candidate_wins"] == 1
    assert report["by_risk_level"]["high"]["candidate_wins"] == 1


def test_pairwise_baseline_wins_on_higher_score(tmp_path: Path) -> None:
    baseline = tmp_path / "baseline"
    candidate = tmp_path / "candidate"
    _write_run(baseline, passed=True, score=0.9, output="better")
    _write_run(candidate, passed=True, score=0.6, output="worse")

    report = compare_pairwise(baseline, candidate)

    assert report["summary"]["baseline_wins"] == 1
    assert report["items"][0]["reason"] == "average score delta -0.30"


def test_pairwise_ties_when_scores_equal(tmp_path: Path) -> None:
    baseline = tmp_path / "baseline"
    candidate = tmp_path / "candidate"
    _write_run(baseline, passed=True, score=1.0, output="same")
    _write_run(candidate, passed=True, score=1.0, output="same")

    report = compare_pairwise(baseline, candidate)

    assert report["summary"]["ties"] == 1
    assert report["items"][0]["winner"] == "tie"


def test_pairwise_writers(tmp_path: Path) -> None:
    baseline = tmp_path / "baseline"
    candidate = tmp_path / "candidate"
    _write_run(baseline, passed=False, score=0.2)
    _write_run(candidate, passed=True, score=1.0)
    report = compare_pairwise(baseline, candidate)

    write_pairwise_json(tmp_path / "pairwise.json", report)
    write_pairwise_markdown(tmp_path / "pairwise.md", report)
    write_pairwise_html(tmp_path / "pairwise.html", report)

    assert json.loads((tmp_path / "pairwise.json").read_text(encoding="utf-8"))["summary"]["candidate_wins"] == 1
    assert "Pairwise Preference Report" in (tmp_path / "pairwise.md").read_text(encoding="utf-8")
    assert "AgentEval Pairwise Preference Report" in (tmp_path / "pairwise.html").read_text(encoding="utf-8")


class FakePairwiseClient:
    async def judge(self, context, config):
        return {"winner": "candidate", "confidence": 0.88, "reasoning": "candidate is clearer", "evidence": ["better answer"], "human_review_recommended": False}


def test_pairwise_judge_client_and_cache(tmp_path: Path) -> None:
    config = PairwiseJudgeConfig(cache={"enabled": True, "cache_dir": tmp_path / "cache"})
    context = {"case": {"id": "c1"}, "baseline": {"final_output": "a"}, "candidate": {"final_output": "b"}}

    first = run_pairwise_judge(context, config, FakePairwiseClient())
    second = run_pairwise_judge(context, config, FakePairwiseClient())

    assert first["winner"] == "candidate"
    assert first["judge"]["cached"] is False
    assert second["judge"]["cached"] is True
