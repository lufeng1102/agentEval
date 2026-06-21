import json

from typer.testing import CliRunner

from cli import app
from tests.review_helpers import write_run


runner = CliRunner()


def test_transcripts_cli_writes_markdown_and_json(tmp_path):
    run_dir = write_run(tmp_path / "run")
    out = tmp_path / "transcripts.md"

    result = runner.invoke(app, ["transcripts", "--run", str(run_dir), "--out", str(out), "--format", "markdown", "--format", "json"])

    assert result.exit_code == 0, result.output
    assert out.exists()
    json_path = tmp_path / "transcripts.json"
    assert json_path.exists()
    payload = json.loads(json_path.read_text(encoding="utf-8"))
    assert payload["summary"]["items"] == 1
    assert payload["items"][0]["case_id"] == "c_fail"


def test_transcripts_cli_writes_html_workbench(tmp_path):
    run_dir = write_run(tmp_path / "run")
    out = tmp_path / "transcripts.html"

    result = runner.invoke(app, ["transcripts", "--run", str(run_dir), "--out", str(out), "--format", "html"])

    assert result.exit_code == 0, result.output
    body = out.read_text(encoding="utf-8")
    assert "AgentEval Transcript Workbench" in body
    assert "c_fail" in body


    run_dir = write_run(tmp_path / "run")
    out = tmp_path / "all.json"

    result = runner.invoke(app, ["transcripts", "--run", str(run_dir), "--out", str(out), "--format", "json", "--all", "--case", "c_pass"])

    assert result.exit_code == 0, result.output
    payload = json.loads(out.read_text(encoding="utf-8"))
    assert payload["summary"]["items"] == 1
    assert payload["items"][0]["case_id"] == "c_pass"
