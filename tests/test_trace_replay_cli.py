import json

import yaml
from typer.testing import CliRunner

from cli import app


runner = CliRunner()


def _write_trace_inputs(tmp_path):
    traces = tmp_path / "traces.jsonl"
    traces.write_text(
        "\n".join(
            [
                json.dumps(
                    {
                        "trace_id": "t1",
                        "source": "otel",
                        "input": "refund",
                        "final_output": "done",
                        "spans": [
                            {"span_id": "s1", "trace_id": "t1", "name": "agent", "kind": "agent", "status": "ok"},
                            {"span_id": "s2", "trace_id": "t1", "name": "search", "kind": "tool", "status": "ok"},
                        ],
                    }
                ),
                json.dumps(
                    {
                        "trace_id": "t2",
                        "source": "otel",
                        "input": "cancel",
                        "final_output": "failed",
                        "spans": [
                            {"span_id": "s3", "trace_id": "t2", "name": "cancel", "kind": "tool", "status": "error", "error": "boom"},
                        ],
                    }
                ),
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    config = tmp_path / "config.yaml"
    config.write_text(
        yaml.safe_dump(
            {
                "agent": {"provider": "static", "static_response": "unused"},
                "evaluators": [{"type": "span"}],
                "report": {"formats": ["json", "markdown"]},
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    return traces, config


def test_trace_import_cli_writes_json_jsonl_and_markdown(tmp_path):
    traces, _ = _write_trace_inputs(tmp_path)
    out = tmp_path / "import.json"

    result = runner.invoke(app, ["trace-import", "--input", str(traces), "--source", "agenteval", "--out", str(out), "--format", "json", "--format", "jsonl", "--format", "markdown"])

    assert result.exit_code == 0, result.output
    assert out.exists()
    assert (tmp_path / "import.jsonl").exists()
    assert (tmp_path / "import.md").exists()
    payload = json.loads(out.read_text(encoding="utf-8"))
    assert payload["summary"]["traces"] == 2
    assert payload["summary"]["spans"] == 3


def test_trace_to_regressions_cli_writes_yaml(tmp_path):
    traces, _ = _write_trace_inputs(tmp_path)
    out = tmp_path / "regressions.yaml"

    result = runner.invoke(app, ["trace-to-regressions", "--traces", str(traces), "--source", "agenteval", "--out", str(out)])

    assert result.exit_code == 0, result.output
    dataset = yaml.safe_load(out.read_text(encoding="utf-8"))
    assert len(dataset["cases"]) == 1
    assert dataset["cases"][0]["id"] == "trace_t2"


def test_trace_replay_cli_writes_run_artifacts_and_threshold_fails(tmp_path):
    traces, config = _write_trace_inputs(tmp_path)
    out = tmp_path / "replay"
    dataset_out = tmp_path / "replay-dataset.yaml"

    result = runner.invoke(app, ["trace-replay", "--traces", str(traces), "--source", "agenteval", "--config", str(config), "--out", str(out), "--dataset-out", str(dataset_out), "--min-pass-rate", "0.4"])

    assert result.exit_code == 0, result.output
    assert (out / "traces.jsonl").exists()
    assert (out / "results.jsonl").exists()
    assert (out / "report.json").exists()
    assert dataset_out.exists()

    failing = runner.invoke(app, ["trace-replay", "--traces", str(traces), "--source", "agenteval", "--config", str(config), "--out", str(tmp_path / "replay-fail"), "--min-pass-rate", "1.0"])

    assert failing.exit_code == 1
    assert "Threshold failed" in failing.output
