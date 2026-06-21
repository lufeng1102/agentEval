import asyncio

from config import EnvironmentConfig, EvaluatorConfig
from environments.browser import _resolve_url, prepare_browser_environment
from environments.models import BrowserCheckResult
from evaluators import BrowserEvaluator, build_evaluator
from reporters.json_reporter import summarize
from schemas import AgentRun, EvalCase, EvalResult, ToolCall


def test_browser_evaluator_passes_text_url_title_attribute_and_screenshot() -> None:
    case = EvalCase(
        id="browser1",
        input="check UI",
        expected={
            "browser": {
                "max_browser_failures": 0,
                "required_url": [{"contains": "index.html"}],
                "required_title": [{"contains": "Dashboard"}],
                "required_text": [{"selector": "#status", "contains": "Saved"}],
                "forbidden_text": [{"contains": "Error"}],
                "required_selectors": ["#status"],
                "required_attributes": [{"selector": "[data-testid=confirmation]", "attribute": "data-state", "value": "complete"}],
                "required_screenshots": 1,
            }
        },
    )
    run = AgentRun(
        case_id="browser1",
        artifacts={
            "environment": {
                "browser": [
                    {"phase": "test", "url": "file:///tmp/index.html", "title": "Dashboard", "status": "ok", "selector": "#status", "text": "Saved", "attribute": None, "attribute_value": None, "screenshot_path": "/tmp/s.png", "error": None},
                    {"phase": "test", "url": "file:///tmp/index.html", "title": "Dashboard", "status": "ok", "selector": "[data-testid=confirmation]", "text": "Done", "attribute": "data-state", "attribute_value": "complete", "screenshot_path": None, "error": None},
                ]
            }
        },
    )

    result = asyncio.run(BrowserEvaluator().evaluate(case, run))

    assert result.passed is True
    assert result.metrics["browser_checks"] == 2
    assert result.metrics["screenshots"] == 1


def test_browser_evaluator_checks_storage_trace_and_tool_choice() -> None:
    case = EvalCase(
        id="browser2",
        input="check UI",
        expected={
            "browser": {
                "required_storage": [{"key": "cart", "value": "full"}],
                "required_traces": 1,
                "tool_choice": {"required_tools": ["screenshot"], "forbidden_tools": ["raw_dom_dump"]},
            }
        },
    )
    run = AgentRun(
        case_id="browser2",
        tool_calls=[ToolCall(name="screenshot")],
        artifacts={"environment": {"browser": [{"phase": "test", "status": "ok", "storage": {"cart": "full", "auth": {"token": "abc"}}, "trace_path": "trace.zip", "error": None}]}},
    )

    result = asyncio.run(BrowserEvaluator().evaluate(case, run))

    assert result.passed is True
    assert result.metrics["traces"] == 1


def test_browser_evaluator_checks_nested_storage_path() -> None:
    case = EvalCase(id="browser3", input="check UI", expected={"browser": {"required_storage": [{"path": "auth.token", "value": "abc"}]}})
    run = AgentRun(case_id="browser3", artifacts={"environment": {"browser": [{"phase": "test", "status": "ok", "storage": {"auth": {"token": "abc"}}, "error": None}]}})

    result = asyncio.run(BrowserEvaluator().evaluate(case, run))

    assert result.passed is True


    case = EvalCase(id="browser1", input="check UI", expected={"browser": {"forbidden_text": [{"contains": "Error"}], "required_selectors": ["#status"]}})
    run = AgentRun(case_id="browser1", artifacts={"environment": {"browser": [{"phase": "test", "url": "file:///tmp/index.html", "status": "ok", "selector": "body", "text": "Error happened", "error": None}]}})

    result = asyncio.run(BrowserEvaluator().evaluate(case, run))

    assert result.passed is False
    assert result.failure_type == "browser_violation"
    assert "forbidden browser text" in result.failure_reason
    assert "required browser selector" in result.failure_reason


def test_browser_evaluator_supports_expected_under_environment_browser() -> None:
    case = EvalCase(
        id="browser1",
        input="check UI",
        expected={"environment": {"browser": {"required_text": [{"selector": "#status", "contains": "Saved"}], "max_browser_failures": 0}}},
    )
    run = AgentRun(case_id="browser1", artifacts={"environment": {"browser": [{"phase": "test", "url": "file:///tmp/index.html", "status": "ok", "selector": "#status", "text": "Saved", "error": None}]}})

    result = asyncio.run(BrowserEvaluator().evaluate(case, run))

    assert result.passed is True


def test_browser_evaluator_counts_browser_failures() -> None:
    case = EvalCase(id="browser1", input="check UI", expected={"browser": {"max_browser_failures": 0}})
    run = AgentRun(case_id="browser1", artifacts={"environment": {"browser": [{"phase": "test", "url": None, "status": "error", "selector": "#status", "text": "", "error": "Timeout"}]}})

    result = asyncio.run(BrowserEvaluator().evaluate(case, run))

    assert result.passed is False
    assert result.metrics["browser_failures"] == 1
    assert "browser failures 1 exceeds max 0" in result.failure_reason


def test_browser_evaluator_fails_required_attribute_value() -> None:
    case = EvalCase(id="browser1", input="check UI", expected={"browser": {"required_attributes": [{"selector": "#save", "attribute": "aria-disabled", "value": "false"}]}})
    run = AgentRun(case_id="browser1", artifacts={"environment": {"browser": [{"phase": "test", "url": "file:///tmp/index.html", "status": "ok", "selector": "#save", "text": "Save", "attribute": "aria-disabled", "attribute_value": "true", "error": None}]}})

    result = asyncio.run(BrowserEvaluator().evaluate(case, run))

    assert result.passed is False
    assert "required browser attribute not matched" in result.failure_reason


def test_browser_url_resolution_prefers_absolute_url_and_base_url(tmp_path) -> None:
    root = tmp_path / "workspace"
    root.mkdir()

    assert _resolve_url(root, "http://example.test/app", {"url": "https://override.test/page"}) == "https://override.test/page"
    assert _resolve_url(root, "http://example.test/app", {"path": "checkout"}) == "http://example.test/app/checkout"
    assert _resolve_url(root, None, {"path": "index.html"}).startswith("file://")


def test_browser_artifact_summary_includes_browser_counts(tmp_path) -> None:
    fixture = tmp_path / "fixture"
    fixture.mkdir()
    prepared = prepare_browser_environment(EvalCase(id="c1", input="open"), 0, tmp_path / "run", EnvironmentConfig(type="browser", fixture=fixture))
    prepared.record.browser.append(
        BrowserCheckResult(
            phase="test",
            url="file:///tmp/index.html",
            status="ok",
            selector="#status",
            text="Saved",
            screenshot_path="shot.png",
        )
    )
    prepared.record.browser.append(BrowserCheckResult(phase="test", status="error", error="boom"))

    summary = prepared.artifact_summary()

    assert summary["summary"]["browser_checks"] == 2
    assert summary["summary"]["browser_failures"] == 1
    assert summary["summary"]["browser_screenshots"] == 1


def test_prepare_browser_environment_copies_fixture_and_records_missing_dependency(tmp_path) -> None:
    fixture = tmp_path / "fixture"
    fixture.mkdir()
    (fixture / "index.html").write_text("<h1>Hello</h1>", encoding="utf-8")
    prepared = prepare_browser_environment(
        EvalCase(id="case/1", input="open"),
        0,
        tmp_path / "run",
        EnvironmentConfig(type="browser", fixture=fixture, test_checks=[{"path": "index.html", "selector": "h1"}]),
    )

    assert (prepared.root / "index.html").exists()
    asyncio.run(prepared.run_checks("test", prepared.test_checks))
    if prepared.record.browser[0].error:
        assert "browser environment requires optional dependency" in prepared.record.browser[0].error
    else:
        assert prepared.record.browser[0].text == "Hello"


def test_build_evaluator_supports_browser() -> None:
    assert isinstance(build_evaluator(EvaluatorConfig(type="browser")), BrowserEvaluator)


def test_report_summary_includes_browser_counts() -> None:
    summary = summarize(
        [EvalCase(id="c1", input="x")],
        [AgentRun(case_id="c1", artifacts={"environment": {"browser": [{"status": "error", "error": "boom", "screenshot_path": "s.png"}]}})],
        [EvalResult(case_id="c1", evaluator="browser", score=0, passed=False)],
    )

    assert summary["environment"]["browser_checks"] == 1
    assert summary["environment"]["browser_failures"] == 1
    assert summary["environment"]["browser_screenshots"] == 1
