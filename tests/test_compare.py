import json
from pathlib import Path

from typer.testing import CliRunner

from cli import app
from compare import compare_runs, write_compare_html, write_compare_json, write_compare_markdown


def _write_report(path: Path, pass_rate: float, avg_score: float, results: list[dict]) -> None:
    path.mkdir(parents=True, exist_ok=True)
    payload = {
        "summary": {
            "pass_rate": pass_rate,
            "avg_score": avg_score,
            "latency_ms": {"p50": 100, "p95": 200},
            "usage": {"total_input_tokens": 10, "output_tokens": 5},
            "by_capability": {"refund": {"results": 1, "pass_rate": pass_rate, "avg_score": avg_score}},
            "by_risk_level": {"high": {"results": 1, "pass_rate": pass_rate, "avg_score": avg_score}},
        },
        "results": results,
    }
    (path / "report.json").write_text(json.dumps(payload), encoding="utf-8")


def test_compare_runs_reports_deltas_and_status_changes(tmp_path: Path) -> None:
    baseline = tmp_path / "baseline"
    candidate = tmp_path / "candidate"
    _write_report(baseline, 0.5, 0.5, [{"case_id": "c1", "evaluator": "contains", "passed": False}])
    _write_report(candidate, 1.0, 0.8, [{"case_id": "c1", "evaluator": "contains", "passed": True}])

    comparison = compare_runs(baseline, candidate)

    assert comparison["delta"]["pass_rate"] == 0.5
    assert comparison["delta"]["by_capability"]["refund"]["pass_rate"] == 0.5
    assert comparison["delta"]["by_risk_level"]["high"]["avg_score"] == 0.30000000000000004
    assert comparison["newly_passed"] == ["c1::contains"]
    assert comparison["newly_failed"] == []


def test_write_compare_markdown(tmp_path: Path) -> None:
    comparison = {
        "baseline": "base",
        "candidate": "cand",
        "delta": {"pass_rate": 0, "avg_score": 0, "latency_p50_ms": 0, "latency_p95_ms": 0, "total_tokens": 0},
        "newly_failed": ["c1::contains"],
        "newly_passed": [],
    }
    path = tmp_path / "compare.md"

    write_compare_markdown(path, comparison)

    assert "AgentEval Compare Report" in path.read_text(encoding="utf-8")


def test_write_compare_json_and_html(tmp_path: Path) -> None:
    comparison = {
        "baseline": "base",
        "candidate": "cand",
        "delta": {"pass_rate": -0.1, "avg_score": -0.2, "latency_p50_ms": 10, "latency_p95_ms": 20, "total_tokens": 30},
        "newly_failed": ["c1::contains"],
        "newly_passed": ["c2::safety"],
    }
    json_path = tmp_path / "compare.json"
    html_path = tmp_path / "compare.html"

    write_compare_json(json_path, comparison)
    write_compare_html(html_path, comparison)

    assert json.loads(json_path.read_text(encoding="utf-8"))["newly_failed"] == ["c1::contains"]
    html = html_path.read_text(encoding="utf-8")
    assert "AgentEval Compare Report" in html
    assert "c1::contains" in html

def test_compare_includes_agent_version_delta(tmp_path: Path) -> None:
    baseline = tmp_path / "baseline"
    candidate = tmp_path / "candidate"
    _write_report(baseline, 1.0, 1.0, [{"case_id": "c1", "evaluator": "contains", "passed": True}])
    _write_report(candidate, 1.0, 1.0, [{"case_id": "c1", "evaluator": "contains", "passed": True}])
    (baseline / "manifest.json").write_text(json.dumps({"agent_version": {"version": "v1", "prompt_version": "p1"}}), encoding="utf-8")
    (candidate / "manifest.json").write_text(json.dumps({"agent_version": {"version": "v2", "prompt_version": "p1"}}), encoding="utf-8")

    comparison = compare_runs(baseline, candidate)
    md_path = tmp_path / "compare-version.md"
    html_path = tmp_path / "compare-version.html"
    write_compare_markdown(md_path, comparison)
    write_compare_html(html_path, comparison)

    assert comparison["agent_version_delta"] == {"version": {"baseline": "v1", "candidate": "v2"}}
    assert "Agent Version Delta" in md_path.read_text(encoding="utf-8")
    assert "Agent Version Delta" in html_path.read_text(encoding="utf-8")



    baseline = tmp_path / "baseline"
    candidate = tmp_path / "candidate"
    _write_report(baseline, 1.0, 1.0, [{"case_id": "c1", "evaluator": "contains", "passed": True}])
    _write_report(candidate, 0.9, 0.9, [{"case_id": "c1", "evaluator": "contains", "passed": False}])
    runner = CliRunner()

    ok = runner.invoke(app, ["compare", "--baseline", str(baseline), "--candidate", str(candidate), "--out", str(tmp_path / "ok.md"), "--max-pass-rate-drop", "0.2"])
    fail = runner.invoke(app, ["compare", "--baseline", str(baseline), "--candidate", str(candidate), "--out", str(tmp_path / "fail.md"), "--max-pass-rate-drop", "0.05", "--fail-on-new-failures"])
    multi = runner.invoke(app, ["compare", "--baseline", str(baseline), "--candidate", str(candidate), "--out", str(tmp_path / "compare"), "--format", "json", "--format", "html"])

    assert ok.exit_code == 0, ok.output
    assert fail.exit_code == 1
    assert "Compare threshold failed" in fail.output
    assert multi.exit_code == 0, multi.output
    assert (tmp_path / "compare.json").exists()
    assert (tmp_path / "compare.html").exists()
