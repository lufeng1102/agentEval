from __future__ import annotations

import shutil
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urljoin

from config import EnvironmentConfig
from environments.filesystem import _merged_environment, _run_command
from environments.models import BrowserCheckResult, EnvironmentSessionRecord
from schemas import EvalCase


@dataclass
class PreparedBrowserEnvironment:
    record: EnvironmentSessionRecord
    setup_commands: list[str]
    test_commands: list[str]
    teardown_commands: list[str]
    setup_checks: list[dict[str, Any]]
    test_checks: list[dict[str, Any]]
    teardown_checks: list[dict[str, Any]]
    base_url: str | None
    command_timeout_seconds: float
    max_command_output_chars: int
    browser_timeout_seconds: float
    browser_headless: bool
    browser_viewport: dict[str, Any]
    browser_screenshot: bool
    browser_trace: bool = False

    @property
    def root(self) -> Path:
        return Path(self.record.root)

    def snapshot_before(self) -> None:
        return None

    def snapshot_after(self) -> None:
        return None

    def compute_diff(self) -> None:
        return None

    async def run_commands(self, phase: str, commands: list[str] | None = None) -> None:
        for command in commands if commands is not None else []:
            self.record.commands.append(await _run_command(self.root, phase, command, self.command_timeout_seconds, self.max_command_output_chars))
        await self.run_checks(phase, _checks_for_phase(self, phase))

    async def run_checks(self, phase: str, checks: list[dict[str, Any]] | None = None) -> None:
        if not checks:
            return
        try:
            from playwright.async_api import async_playwright
        except ImportError:
            message = "browser environment requires optional dependency: pip install -e '.[browser]' && python -m playwright install chromium"
            for check in checks:
                self.record.browser.append(BrowserCheckResult(phase=phase, url=_resolve_url(self.root, self.base_url, check), status="error", selector=check.get("selector"), attribute=check.get("attribute"), error=message))
            return

        try:
            async with async_playwright() as playwright:
                browser = await playwright.chromium.launch(headless=self.browser_headless)
                context = await browser.new_context(viewport=self.browser_viewport or None)
                if self.browser_trace:
                    await context.tracing.start(screenshots=True, snapshots=True, sources=True)
                page = await context.new_page()
                try:
                    for index, check in enumerate(checks):
                        self.record.browser.append(await _run_browser_check(page, context, self.root, self.base_url, phase, index, check, self.browser_timeout_seconds, self.browser_screenshot, self.max_command_output_chars))
                finally:
                    if self.browser_trace:
                        traces_dir = self.root.parent / "traces"
                        traces_dir.mkdir(parents=True, exist_ok=True)
                        trace_path = traces_dir / f"{phase}.zip"
                        await context.tracing.stop(path=str(trace_path))
                        for check in self.record.browser:
                            if check.phase == phase and (check.trace_path is None or check.trace_path == "pending"):
                                check.trace_path = str(trace_path)
                    await context.close()
                    await browser.close()
        except Exception as exc:
            message = f"{exc.__class__.__name__}: {exc}"
            for check in checks:
                self.record.browser.append(BrowserCheckResult(phase=phase, url=_resolve_url(self.root, self.base_url, check), status="error", selector=check.get("selector"), attribute=check.get("attribute"), error=message))

    def artifact_summary(self) -> dict[str, Any]:
        command_failures = [command for command in self.record.commands if command.timed_out or (command.exit_code is not None and command.exit_code != 0) or command.exit_code is None]
        browser_failures = [check for check in self.record.browser if check.error or check.status != "ok"]
        return {
            "type": self.record.type,
            "fixture": self.record.fixture,
            "root": self.record.root,
            "base_url": self.base_url,
            "case_id": self.record.case_id,
            "repeat_index": self.record.repeat_index,
            "commands": [command.model_dump(mode="json") for command in self.record.commands],
            "database": [query.model_dump(mode="json") for query in self.record.database],
            "http": [check.model_dump(mode="json") for check in self.record.http],
            "browser": [check.model_dump(mode="json") for check in self.record.browser],
            "summary": {
                "commands": len(self.record.commands),
                "command_failures": len(command_failures),
                "queries": len(self.record.database),
                "query_failures": sum(1 for query in self.record.database if query.error),
                "http_checks": len(self.record.http),
                "http_failures": sum(1 for check in self.record.http if check.error or check.status_code is None),
                "browser_checks": len(self.record.browser),
                "browser_failures": len(browser_failures),
                "browser_screenshots": sum(1 for check in self.record.browser if check.screenshot_path),
            },
        }


def prepare_browser_environment(case: EvalCase, repeat_index: int, output_dir: str | Path, config: EnvironmentConfig) -> PreparedBrowserEnvironment:
    merged = _merged_environment(config, case)
    session_dir = Path(output_dir) / "envs" / _safe_id(case.id) / str(repeat_index)
    if session_dir.exists():
        shutil.rmtree(session_dir)
    session_dir.mkdir(parents=True, exist_ok=True)
    workspace = session_dir / "workspace"
    fixture = merged.get("fixture")
    if fixture:
        fixture_path = Path(fixture)
        shutil.copytree(fixture_path, workspace)
    else:
        fixture_path = None
        workspace.mkdir(parents=True, exist_ok=True)
    viewport = merged.get("browser_viewport") or {"width": 1280, "height": 720}
    return PreparedBrowserEnvironment(
        record=EnvironmentSessionRecord(case_id=case.id, repeat_index=repeat_index, type="browser", fixture=str(fixture_path) if fixture_path else None, root=str(workspace)),
        setup_commands=[str(item) for item in merged.get("setup_commands", [])],
        test_commands=[str(item) for item in merged.get("test_commands", [])],
        teardown_commands=[str(item) for item in merged.get("teardown_commands", [])],
        setup_checks=[dict(item) for item in merged.get("setup_checks", []) or []],
        test_checks=[dict(item) for item in merged.get("test_checks", []) or []],
        teardown_checks=[dict(item) for item in merged.get("teardown_checks", []) or []],
        base_url=str(merged.get("base_url")) if merged.get("base_url") else None,
        command_timeout_seconds=float(merged.get("command_timeout_seconds", 120)),
        max_command_output_chars=int(merged.get("max_command_output_chars", 20000)),
        browser_timeout_seconds=float(merged.get("browser_timeout_seconds", 30)),
        browser_headless=bool(merged.get("browser_headless", True)),
        browser_viewport=dict(viewport) if isinstance(viewport, dict) else {"width": 1280, "height": 720},
        browser_screenshot=bool(merged.get("browser_screenshot", False)),
        browser_trace=bool(merged.get("browser_trace", False)),
    )


def _checks_for_phase(prepared: PreparedBrowserEnvironment, phase: str) -> list[dict[str, Any]]:
    if phase == "setup":
        return prepared.setup_checks
    if phase == "test":
        return prepared.test_checks
    if phase == "teardown":
        return prepared.teardown_checks
    return []


async def _run_browser_check(page, context, root: Path, base_url: str | None, phase: str, index: int, spec: dict[str, Any], default_timeout_seconds: float, default_screenshot: bool, max_chars: int) -> BrowserCheckResult:
    started = time.perf_counter()
    target_url = _resolve_url(root, base_url, spec)
    selector = spec.get("selector")
    attribute = spec.get("attribute")
    screenshot_path = None
    trace_path = None
    check_type = str(spec.get("type") or spec.get("check_type") or "page")
    title = None
    text = ""
    html = ""
    attribute_value = None
    storage: dict[str, Any] = {}
    cookies: list[dict[str, Any]] = []
    error = None
    status = "ok"
    try:
        timeout_ms = int(float(spec.get("timeout_seconds") or default_timeout_seconds) * 1000)
        if not target_url:
            raise ValueError("browser check requires url or path")
        await page.goto(target_url, wait_until=str(spec.get("wait_until") or "load"), timeout=timeout_ms)
        if spec.get("wait_for_selector"):
            await page.wait_for_selector(str(spec["wait_for_selector"]), timeout=timeout_ms)
        locator = page.locator(str(selector)).first if selector else page.locator("body").first
        title = await page.title()
        text = _truncate(await locator.inner_text(timeout=timeout_ms), max_chars)
        html = _truncate(await locator.evaluate("node => node.outerHTML"), max_chars)
        if attribute:
            attribute_value = await locator.get_attribute(str(attribute), timeout=timeout_ms)
        storage = await page.evaluate("() => Object.fromEntries(Object.entries(window.localStorage || {}))")
        cookies = await context.cookies()
        if bool(spec.get("screenshot", default_screenshot)):
            screenshots_dir = root.parent / "screenshots"
            screenshots_dir.mkdir(parents=True, exist_ok=True)
            screenshot_file = screenshots_dir / f"{phase}-{index}.png"
            await page.screenshot(path=str(screenshot_file), full_page=bool(spec.get("full_page", True)))
            screenshot_path = str(screenshot_file)
        if bool(spec.get("trace", False)):
            trace_path = "pending"
    except Exception as exc:  # keep suite running; evaluator decides pass/fail
        status = "error"
        error = f"{exc.__class__.__name__}: {exc}"
    return BrowserCheckResult(phase=phase, check_type=check_type, url=page.url or target_url, title=title, status=status, selector=str(selector) if selector else None, text=text, html=html, attribute=str(attribute) if attribute else None, attribute_value=attribute_value, storage=storage, cookies=cookies, screenshot_path=screenshot_path, trace_path=trace_path, error=error, duration_ms=int((time.perf_counter() - started) * 1000))


def _resolve_url(root: Path, base_url: str | None, spec: dict[str, Any]) -> str | None:
    if spec.get("url"):
        return str(spec["url"])
    if spec.get("path") is None:
        return None
    path = str(spec["path"])
    if base_url:
        return urljoin(base_url.rstrip("/") + "/", path.lstrip("/"))
    return (root / path.lstrip("/")).resolve().as_uri()


def _truncate(value: str, max_chars: int) -> str:
    if max_chars < 0 or len(value) <= max_chars:
        return value
    return value[:max_chars] + "\n...[truncated]"


def _safe_id(case_id: str) -> str:
    safe = "".join(char if char.isalnum() or char in {"-", "_", "."} else "_" for char in case_id)
    return safe or "case"
