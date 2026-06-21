from review.transcripts import build_transcript_review, write_transcript_review_markdown
from tests.review_helpers import write_run


def test_transcript_review_builds_failed_trace_with_dynamic_and_environment(tmp_path):
    run_dir = write_run(tmp_path / "run")

    report = build_transcript_review(run_dir)

    assert report["summary"]["items"] == 1
    item = report["items"][0]
    assert item["case_id"] == "c_fail"
    assert item["failed"] is True
    assert item["messages"][1]["role"] == "assistant"
    assert item["tool_calls"][0]["name"] == "lookup"
    assert item["dynamic"]["stop_reason"] == "max_turns"
    assert item["dynamic"]["simulator_turns"] == 1
    assert item["environment"]["summary"]["command_failures"] == 1
    assert "unsafe" in item["suggested_focus"]


def test_transcript_review_can_include_all_and_filter_evaluator(tmp_path):
    run_dir = write_run(tmp_path / "run")

    report = build_transcript_review(run_dir, failed_only=False, evaluators=["contains"])

    assert report["summary"]["items"] == 2
    by_case = {item["case_id"]: item for item in report["items"]}
    assert by_case["c_pass"]["results"][0]["evaluator"] == "contains"
    assert by_case["c_fail"]["results"][0]["failure_type"] == "missing_evaluator_result"


def test_transcript_review_markdown_writer(tmp_path):
    run_dir = write_run(tmp_path / "run")
    report = build_transcript_review(run_dir)
    out = tmp_path / "transcripts.md"

    write_transcript_review_markdown(out, report)

    text = out.read_text(encoding="utf-8")
    assert "AgentEval Transcript Review" in text
    assert "c_fail" in text
    assert "Dynamic scenario" in text
    assert "Environment" in text
