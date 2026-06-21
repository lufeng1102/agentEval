import json

from typer.testing import CliRunner

from cli import app
from tests.review_helpers import write_run


runner = CliRunner()


def test_review_cli_sample_import_and_calibration(tmp_path):
    run_dir = write_run(tmp_path / "run")
    queue_path = tmp_path / "queue.jsonl"

    sample = runner.invoke(app, ["review-sample", "--run", str(run_dir), "--out", str(queue_path), "--format", "jsonl", "--format", "markdown", "--format", "html", "--strategy", "random"])
    assert sample.exit_code == 0, sample.output
    assert queue_path.exists()
    assert (tmp_path / "queue.md").exists()
    assert (tmp_path / "queue.html").exists()
    html = (tmp_path / "queue.html").read_text(encoding="utf-8")
    assert "Annotation Queue" in html
    assert "review_label_v1" in html
    queue_items = [json.loads(line) for line in queue_path.read_text(encoding="utf-8").splitlines()]

    labels_path = tmp_path / "labels.jsonl"
    labels_path.write_text(
        "\n".join(
            json.dumps({"review_id": item["review_id"], "case_id": item["case_id"], "repeat_index": item["repeat_index"], "human_passed": bool(index % 2), "human_score": 0.9 if index % 2 else 0.1, "human_reason": "label"})
            for index, item in enumerate(queue_items)
        )
        + "\n",
        encoding="utf-8",
    )
    human_path = tmp_path / "human-review.json"
    imported = runner.invoke(app, ["review-import", "--queue", str(queue_path), "--labels", str(labels_path), "--out", str(human_path), "--format", "json", "--format", "markdown"])
    assert imported.exit_code == 0, imported.output
    assert human_path.exists()
    assert (tmp_path / "human-review.md").exists()

    calibration_path = tmp_path / "judge-calibration.md"
    calibrated = runner.invoke(app, ["judge-calibration", "--run", str(run_dir), "--human-review", str(human_path), "--out", str(calibration_path), "--format", "markdown", "--format", "json"])
    assert calibrated.exit_code == 0, calibrated.output
    assert calibration_path.exists()


def test_review_queue_html_escapes_content(tmp_path):
    run_dir = write_run(tmp_path / "run")
    report_path = run_dir / "report.json"
    report = json.loads(report_path.read_text(encoding="utf-8"))
    report["cases"][0]["input"] = "<script>alert('case')</script>"
    report_path.write_text(json.dumps(report), encoding="utf-8")
    traces_path = run_dir / "traces.jsonl"
    traces = [json.loads(line) for line in traces_path.read_text(encoding="utf-8").splitlines()]
    traces[0]["final_output"] = "<img src=x onerror=alert(1)>"
    traces_path.write_text("\n".join(json.dumps(item) for item in traces) + "\n", encoding="utf-8")

    html_path = tmp_path / "queue.html"
    sample = runner.invoke(app, ["review-sample", "--run", str(run_dir), "--out", str(html_path), "--format", "html", "--strategy", "random", "--limit", "1"])

    assert sample.exit_code == 0, sample.output
    html = html_path.read_text(encoding="utf-8")
    assert "&lt;script&gt;alert(&#x27;case&#x27;)&lt;/script&gt;" in html
    assert "&lt;img src=x onerror=alert(1)&gt;" in html
    assert "<script>alert('case')</script>" not in html
