import json
from pathlib import Path

from typer.testing import CliRunner

from cli import app


runner = CliRunner()


def test_flakes_command_reports_flaky_cases(tmp_path: Path) -> None:
    report = tmp_path / "report.json"
    report.write_text(
        json.dumps(
            {
                "summary": {
                    "stability": {
                        "flaky_cases": ["c1"],
                        "pass_at_1": 0.5,
                        "pass_at_k": 1.0,
                        "pass_all": 0.0,
                        "cases": {"c1": {"pass_rate": 0.5, "score_stddev": 0.5, "flaky": True}},
                    }
                }
            }
        ),
        encoding="utf-8",
    )

    result = runner.invoke(app, ["flakes", "--report", str(report)])

    assert result.exit_code == 0, result.output
    assert "Flaky cases: 1" in result.output
    assert "c1" in result.output


def test_dashboard_command_writes_multi_run_html(tmp_path: Path) -> None:
    run_a = tmp_path / "runs" / "a"
    run_b = tmp_path / "runs" / "b"
    run_a.mkdir(parents=True)
    run_b.mkdir(parents=True)
    for run_dir, pass_rate in [(run_a, 0.5), (run_b, 1.0)]:
        (run_dir / "report.json").write_text(
            json.dumps({"summary": {"pass_rate": pass_rate, "avg_score": pass_rate, "failures": int(pass_rate < 1), "latency_ms": {"p50": 100, "p95": 200}, "usage": {"total_input_tokens": 10, "output_tokens": 5}, "errors": {"total": 0}}}),
            encoding="utf-8",
        )
    output = tmp_path / "dashboard.html"

    result = runner.invoke(app, ["dashboard", "--runs", str(tmp_path / "runs"), "--out", str(output)])

    assert result.exit_code == 0, result.output
    html = output.read_text(encoding="utf-8")
    assert "AgentEval Runs Dashboard" in html
    assert "a" in html
    assert "b" in html
    assert "100.00%" in html
