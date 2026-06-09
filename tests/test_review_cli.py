import json

from typer.testing import CliRunner

from cli import app
from tests.review_helpers import write_run


runner = CliRunner()


def test_review_cli_sample_import_and_calibration(tmp_path):
    run_dir = write_run(tmp_path / "run")
    queue_path = tmp_path / "queue.jsonl"

    sample = runner.invoke(app, ["review-sample", "--run", str(run_dir), "--out", str(queue_path), "--format", "jsonl", "--format", "markdown", "--strategy", "random"])
    assert sample.exit_code == 0, sample.output
    assert queue_path.exists()
    assert (tmp_path / "queue.md").exists()
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
    assert (tmp_path / "judge-calibration.json").exists()
