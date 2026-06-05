from pathlib import Path
import json

from typer.testing import CliRunner

from cli import app


runner = CliRunner()


def test_cli_threshold_passes(tmp_path: Path) -> None:
    result = runner.invoke(
        app,
        [
            "run",
            "--dataset",
            "examples/datasets/basic_agent_eval.yaml",
            "--config",
            "examples/configs/static_eval.yaml",
            "--out",
            str(tmp_path / "run"),
            "--min-pass-rate",
            "0.5",
            "--min-score",
            "0.5",
        ],
    )

    assert result.exit_code == 0, result.output
    assert "pass_rate" in result.output
    assert (tmp_path / "run" / "report.html").exists()


def test_cli_threshold_fails_when_pass_rate_too_high(tmp_path: Path) -> None:
    result = runner.invoke(
        app,
        [
            "run",
            "--dataset",
            "examples/datasets/basic_agent_eval.yaml",
            "--config",
            "examples/configs/static_eval.yaml",
            "--out",
            str(tmp_path / "run"),
            "--min-pass-rate",
            "1.0",
        ],
    )

    assert result.exit_code == 1
    assert "Threshold failed" in result.output


def test_cli_fail_on_error_uses_bad_provider(tmp_path: Path) -> None:
    config = tmp_path / "bad-provider.yaml"
    config.write_text(
        """
agent:
  provider: missing
runner:
  concurrency: 1
evaluators:
  - type: contains
report:
  formats: [json]
""".strip(),
        encoding="utf-8",
    )

    result = runner.invoke(
        app,
        [
            "run",
            "--dataset",
            "examples/datasets/basic_agent_eval.yaml",
            "--config",
            str(config),
            "--out",
            str(tmp_path / "run"),
        ],
    )

    assert result.exit_code != 0


def test_cli_converts_json_report_to_html(tmp_path: Path) -> None:
    report = tmp_path / "report.json"
    output = tmp_path / "custom.html"
    report.write_text(
        json.dumps(
            {
                "summary": {
                    "cases": 1,
                    "failures": 0,
                    "pass_rate": 1.0,
                    "avg_score": 1.0,
                    "usage": {"cache_hit_rate": 0.0},
                    "by_evaluator": {"contains": {"results": 1, "pass_rate": 1.0, "avg_score": 1.0}},
                    "by_tag": {},
                    "errors": {"by_case": {}},
                },
                "runs": [{"case_id": "c1", "final_output": "ok"}],
                "results": [{"case_id": "c1", "evaluator": "contains", "score": 1, "passed": True}],
            }
        ),
        encoding="utf-8",
    )

    result = runner.invoke(app, ["html", "--report", str(report), "--out", str(output)])

    assert result.exit_code == 0, result.output
    assert "Wrote HTML report" in result.output
    assert output.exists()
    assert "AgentEval Report" in output.read_text(encoding="utf-8")


def test_cli_html_defaults_to_report_sibling_html(tmp_path: Path) -> None:
    report = tmp_path / "report.json"
    report.write_text(
        json.dumps(
            {
                "summary": {"cases": 0, "failures": 0, "pass_rate": 0.0, "avg_score": 0.0, "usage": {"cache_hit_rate": 0.0}, "by_evaluator": {}, "by_tag": {}, "errors": {"by_case": {}}},
                "runs": [],
                "results": [],
            }
        ),
        encoding="utf-8",
    )

    result = runner.invoke(app, ["html", "--report", str(report)])

    assert result.exit_code == 0, result.output
    assert (tmp_path / "report.html").exists()


def test_cli_html_creates_parent_directory(tmp_path: Path) -> None:
    report = tmp_path / "report.json"
    output = tmp_path / "nested" / "reports" / "report.html"
    report.write_text(
        json.dumps(
            {
                "summary": {"cases": 0, "failures": 0, "pass_rate": 0.0, "avg_score": 0.0, "usage": {"cache_hit_rate": 0.0}, "by_evaluator": {}, "by_tag": {}, "errors": {"by_case": {}}},
                "runs": [],
                "results": [],
            }
        ),
        encoding="utf-8",
    )

    result = runner.invoke(app, ["html", "--report", str(report), "--out", str(output)])

    assert result.exit_code == 0, result.output
    assert output.exists()


def test_cli_html_rejects_invalid_json(tmp_path: Path) -> None:
    report = tmp_path / "report.json"
    report.write_text("{bad json", encoding="utf-8")

    result = runner.invoke(app, ["html", "--report", str(report)])

    assert result.exit_code != 0


def test_cli_filters_run_by_case_and_tag(tmp_path: Path) -> None:
    result = runner.invoke(
        app,
        [
            "run",
            "--dataset",
            "examples/datasets/basic_agent_eval.yaml",
            "--config",
            "examples/configs/static_eval.yaml",
            "--out",
            str(tmp_path / "run"),
            "--case",
            "factual_001",
            "--tag",
            "factuality",
        ],
    )

    assert result.exit_code == 0, result.output
    assert "Completed 1 cases" in result.output


def test_cli_filter_with_no_matching_cases_fails(tmp_path: Path) -> None:
    result = runner.invoke(
        app,
        [
            "run",
            "--dataset",
            "examples/datasets/basic_agent_eval.yaml",
            "--config",
            "examples/configs/static_eval.yaml",
            "--out",
            str(tmp_path / "run"),
            "--tag",
            "missing-tag",
        ],
    )

    assert result.exit_code != 0
    assert "no cases matched filters" in result.output


def test_cli_run_resume_skips_existing_completed_case(tmp_path: Path) -> None:
    run_dir = tmp_path / "run"
    first = runner.invoke(
        app,
        [
            "run",
            "--dataset",
            "examples/datasets/basic_agent_eval.yaml",
            "--config",
            "examples/configs/static_eval.yaml",
            "--out",
            str(run_dir),
            "--case",
            "factual_001",
        ],
    )
    second = runner.invoke(
        app,
        [
            "run",
            "--dataset",
            "examples/datasets/basic_agent_eval.yaml",
            "--config",
            "examples/configs/static_eval.yaml",
            "--out",
            str(run_dir),
            "--case",
            "factual_001",
            "--resume",
        ],
    )

    assert first.exit_code == 0, first.output
    assert second.exit_code == 0, second.output
    assert "Resumed 2 existing runs" in second.output


def test_cli_excludes_cases_by_tag(tmp_path: Path) -> None:
    result = runner.invoke(
        app,
        [
            "run",
            "--dataset",
            "examples/datasets/basic_agent_eval.yaml",
            "--config",
            "examples/configs/static_eval.yaml",
            "--out",
            str(tmp_path / "run"),
            "--exclude-tag",
            "safety",
        ],
    )

    assert result.exit_code == 0, result.output
    assert "Completed 5 cases" in result.output


def test_cli_filters_by_multiple_cases_and_tags(tmp_path: Path) -> None:
    result = runner.invoke(
        app,
        [
            "run",
            "--dataset",
            "examples/datasets/basic_agent_eval.yaml",
            "--config",
            "examples/configs/static_eval.yaml",
            "--out",
            str(tmp_path / "run"),
            "--case",
            "factual_001",
            "--case",
            "tool_001",
            "--tag",
            "factuality",
            "--tag",
            "tool-use",
        ],
    )

    assert result.exit_code == 0, result.output
    assert "Completed 1 cases" in result.output


def test_cli_repeats_option_overrides_config(tmp_path: Path) -> None:
    result = runner.invoke(
        app,
        [
            "run",
            "--dataset",
            "examples/datasets/basic_agent_eval.yaml",
            "--config",
            "examples/configs/static_eval.yaml",
            "--out",
            str(tmp_path / "run"),
            "--case",
            "factual_001",
            "--repeats",
            "3",
        ],
    )

    assert result.exit_code == 0, result.output
    report = json.loads((tmp_path / "run" / "report.json").read_text(encoding="utf-8"))
    assert report["summary"]["runs"] == 3
