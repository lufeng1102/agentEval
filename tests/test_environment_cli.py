import json
from pathlib import Path

from typer.testing import CliRunner

from cli import app


runner = CliRunner()


def _write_fixture(path: Path) -> Path:
    (path / "src").mkdir(parents=True)
    (path / "src" / "auth.py").write_text("old", encoding="utf-8")
    return path


def test_env_validate_accepts_filesystem_config(tmp_path: Path) -> None:
    fixture = _write_fixture(tmp_path / "fixture")
    dataset = tmp_path / "dataset.yaml"
    dataset.write_text("cases:\n  - id: c1\n    input: fix\n    expected:\n      environment:\n        required_files: [src/auth.py]\n", encoding="utf-8")
    config = tmp_path / "config.yaml"
    config.write_text(f"environment:\n  type: filesystem\n  fixture: {fixture}\nevaluators:\n  - type: environment\n", encoding="utf-8")

    result = runner.invoke(app, ["env-validate", "--dataset", str(dataset), "--config", str(config)])

    assert result.exit_code == 0, result.output
    assert "Environment validation passed" in result.output


def test_env_validate_accepts_browser_config(tmp_path: Path) -> None:
    fixture = tmp_path / "browser_fixture"
    fixture.mkdir()
    (fixture / "index.html").write_text("<h1 id='status'>Saved</h1>", encoding="utf-8")
    dataset = tmp_path / "dataset.yaml"
    dataset.write_text("cases:\n  - id: c1\n    input: open\n    expected:\n      browser:\n        required_text:\n          - selector: '#status'\n            contains: Saved\n", encoding="utf-8")
    config = tmp_path / "config.yaml"
    config.write_text(f"environment:\n  type: browser\n  fixture: {fixture}\n  test_checks:\n    - path: index.html\n      selector: '#status'\nevaluators:\n  - type: browser\n", encoding="utf-8")

    result = runner.invoke(app, ["env-validate", "--dataset", str(dataset), "--config", str(config)])

    assert result.exit_code == 0, result.output


def test_env_validate_rejects_invalid_browser_expected(tmp_path: Path) -> None:
    fixture = tmp_path / "browser_fixture"
    fixture.mkdir()
    dataset = tmp_path / "dataset.yaml"
    dataset.write_text("cases:\n  - id: c1\n    input: open\n    expected:\n      browser:\n        max_browser_failures: none\n", encoding="utf-8")
    config = tmp_path / "config.yaml"
    config.write_text(f"environment:\n  type: browser\n  fixture: {fixture}\nevaluators:\n  - type: browser\n", encoding="utf-8")

    result = runner.invoke(app, ["env-validate", "--dataset", str(dataset), "--config", str(config)])

    assert result.exit_code == 1
    assert "expected.browser.max_browser_failures" in result.output


def test_env_validate_rejects_missing_fixture(tmp_path: Path) -> None:
    dataset = tmp_path / "dataset.yaml"
    dataset.write_text("cases:\n  - id: c1\n    input: fix\n    expected:\n      environment: {}\n", encoding="utf-8")
    config = tmp_path / "config.yaml"
    config.write_text(f"environment:\n  type: filesystem\n  fixture: {tmp_path / 'missing'}\nevaluators:\n  - type: environment\n", encoding="utf-8")

    result = runner.invoke(app, ["env-validate", "--dataset", str(dataset), "--config", str(config)])

    assert result.exit_code == 1
    assert "fixture does not exist" in result.output


def test_run_writes_environment_jsonl_and_passes_environment_evaluator(tmp_path: Path) -> None:
    fixture = _write_fixture(tmp_path / "fixture")
    dataset = tmp_path / "dataset.yaml"
    dataset.write_text(
        "cases:\n  - id: c1\n    input: fix\n    metadata:\n      edit_path: src/auth.py\n      edit_content: fixed\n    expected:\n      environment:\n        required_modified_files: [src/auth.py]\n        forbidden_modified_files: [tests/**]\n",
        encoding="utf-8",
    )
    config = tmp_path / "config.yaml"
    config.write_text(
        f"agent:\n  provider: import\n  settings:\n    import_path: tests.imported_agent.build_environment_agent\nenvironment:\n  type: filesystem\n  fixture: {fixture}\n  protected_paths: [tests/**]\nevaluators:\n  - type: environment\nreport:\n  formats: [json]\n",
        encoding="utf-8",
    )
    out = tmp_path / "run"

    result = runner.invoke(app, ["run", "--dataset", str(dataset), "--config", str(config), "--out", str(out)])

    assert result.exit_code == 0, result.output
    assert (out / "environment.jsonl").exists()
    record = json.loads((out / "environment.jsonl").read_text(encoding="utf-8").splitlines()[0])
    assert record["diff"]["modified"] == ["src/auth.py"]
    report = json.loads((out / "report.json").read_text(encoding="utf-8"))
    assert report["summary"]["environment"]["sessions"] == 1
    assert report["results"][0]["passed"] is True


def test_run_fails_environment_evaluator_on_forbidden_path(tmp_path: Path) -> None:
    fixture = _write_fixture(tmp_path / "fixture")
    dataset = tmp_path / "dataset.yaml"
    dataset.write_text("cases:\n  - id: c1\n    input: fix\n    expected:\n      environment:\n        forbidden_modified_files: [tests/**]\n", encoding="utf-8")
    config = tmp_path / "config.yaml"
    config.write_text(
        f"agent:\n  provider: import\n  settings:\n    import_path: tests.imported_agent.build_forbidden_environment_agent\nenvironment:\n  type: filesystem\n  fixture: {fixture}\n  protected_paths: [tests/**]\nevaluators:\n  - type: environment\nreport:\n  formats: [json]\n",
        encoding="utf-8",
    )
    out = tmp_path / "run"

    result = runner.invoke(app, ["run", "--dataset", str(dataset), "--config", str(config), "--out", str(out)])

    assert result.exit_code == 0, result.output
    report = json.loads((out / "report.json").read_text(encoding="utf-8"))
    assert report["results"][0]["passed"] is False
    assert report["summary"]["environment"]["protected_path_violations"] == 1


def test_env_validate_rejects_invalid_command_fields(tmp_path: Path) -> None:
    fixture = _write_fixture(tmp_path / "fixture")
    dataset = tmp_path / "dataset.yaml"
    dataset.write_text("cases:\n  - id: c1\n    input: fix\n    expected:\n      environment:\n        required_command_success: pytest\n", encoding="utf-8")
    config = tmp_path / "config.yaml"
    config.write_text(f"environment:\n  type: filesystem\n  fixture: {fixture}\n  command_timeout_seconds: 0\nevaluators:\n  - type: environment\n", encoding="utf-8")

    result = runner.invoke(app, ["env-validate", "--dataset", str(dataset), "--config", str(config)])

    assert result.exit_code == 1
    assert "command_timeout_seconds" in result.output
    assert "required_command_success" in result.output


def test_env_independence_check_and_clean(tmp_path: Path) -> None:
    fixture = _write_fixture(tmp_path / "fixture")
    dataset = tmp_path / "dataset.yaml"
    dataset.write_text("cases:\n  - id: c1\n    input: fix\n    expected:\n      environment:\n        required_command_success:\n          - python -c \"print('ok')\"\n", encoding="utf-8")
    config = tmp_path / "config.yaml"
    config.write_text(f"environment:\n  type: filesystem\n  fixture: {fixture}\n  test_commands:\n    - python -c \"print('ok')\"\nevaluators:\n  - type: environment\nreport:\n  formats: [json]\n", encoding="utf-8")
    out = tmp_path / "run"
    run_result = runner.invoke(app, ["run", "--dataset", str(dataset), "--config", str(config), "--out", str(out)])
    assert run_result.exit_code == 0, run_result.output

    check_result = runner.invoke(app, ["env-independence-check", "--run", str(out), "--out", str(out / "env-check.json"), "--format", "json"])
    assert check_result.exit_code == 0, check_result.output

    dry_run = runner.invoke(app, ["env-clean", "--run", str(out), "--dry-run", "--out", str(out / "clean.json"), "--format", "json"])
    assert dry_run.exit_code == 0, dry_run.output
    cleanup = json.loads((out / "clean.json").read_text(encoding="utf-8"))
    assert cleanup["planned_delete"]
    assert (out / "envs").exists()

    clean = runner.invoke(app, ["env-clean", "--run", str(out), "--no-dry-run"])
    assert clean.exit_code == 0, clean.output
    assert (out / "environment.jsonl").exists()
    assert not any((out / "envs").iterdir())


def test_env_clean_keep_failures_preserves_failed_case(tmp_path: Path) -> None:
    fixture = _write_fixture(tmp_path / "fixture")
    dataset = tmp_path / "dataset.yaml"
    dataset.write_text("cases:\n  - id: c1\n    input: fix\n    expected:\n      environment:\n        forbidden_modified_files: [tests/**]\n", encoding="utf-8")
    config = tmp_path / "config.yaml"
    config.write_text(f"agent:\n  provider: import\n  settings:\n    import_path: tests.imported_agent.build_forbidden_environment_agent\nenvironment:\n  type: filesystem\n  fixture: {fixture}\n  protected_paths: [tests/**]\nevaluators:\n  - type: environment\nreport:\n  formats: [json]\n", encoding="utf-8")
    out = tmp_path / "run"
    assert runner.invoke(app, ["run", "--dataset", str(dataset), "--config", str(config), "--out", str(out)]).exit_code == 0

    result = runner.invoke(app, ["env-clean", "--run", str(out), "--keep-failures", "--no-dry-run"])

    assert result.exit_code == 0, result.output
    assert (out / "envs" / "c1").exists()
