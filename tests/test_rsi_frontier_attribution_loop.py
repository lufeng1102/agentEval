from pathlib import Path

from rsi.attribution import analyze_attribution
from rsi.evolution_loop import analyze_evolution_loop
from rsi.frontier import analyze_frontier
from tests.rsi_helpers import write_json, write_run


def test_frontier_tracks_capability_difficulty_and_risk(tmp_path: Path) -> None:
    runs = tmp_path / "runs"
    write_run(runs / "v1", pass_rate=1.0, capability="prompt_repair", difficulty=2, risk_level="low")
    write_run(runs / "v2", pass_rate=1.0, capability="prompt_repair", difficulty=4, risk_level=" High ")

    report = analyze_frontier(runs)

    assert report["capabilities"][0]["best_difficulty"] == 4
    assert report["capabilities"][0]["best_safe_difficulty"] == 2
    assert report["warnings"]


def test_attribution_reports_component_effects(tmp_path: Path) -> None:
    baseline = write_run(tmp_path / "baseline", pass_rate=0.5)
    prompt = write_run(tmp_path / "prompt", pass_rate=0.8)
    tool = write_run(tmp_path / "tool", pass_rate=0.7)
    spec = tmp_path / "attr.yaml"
    spec.write_text(f"attribution:\n  baseline:\n    run_dir: {baseline}\n  candidates:\n    - id: prompt\n      run_dir: {prompt}\n      changed_components: [prompt]\n    - id: tool\n      run_dir: {tool}\n      changed_components: [toolset]\n", encoding="utf-8")

    report = analyze_attribution(spec)

    assert report["component_attribution"]["prompt"] == 0.30000000000000004
    assert len(report["candidates"]) == 2


def test_evolution_loop_computes_iteration_metrics(tmp_path: Path) -> None:
    v1 = write_run(tmp_path / "v1", pass_rate=0.5)
    v2 = write_run(tmp_path / "v2", pass_rate=1.0)
    mod = write_json(tmp_path / "mod.json", {"expected_impact": {"fixed_failures": ["r1"]}})
    spec = tmp_path / "loop.yaml"
    spec.write_text(f"evolution_loop:\n  id: loop\n  steps:\n    - iteration: 1\n      input_run: {v1}\n      candidate_run: {v2}\n      modification: {mod}\n      decision: accepted\n", encoding="utf-8")

    report = analyze_evolution_loop(spec)

    assert report["iterations"] == 1
    assert report["accepted"] == 1
    assert report["fixed_regressions"] == ["r1"]
    assert report["accepted_rate"] == 1.0
    assert report["steps"][0]["pass_rate_delta"] == 0.5
    assert report["risk_level"] == "low"


def test_evolution_loop_flags_high_or_critical_risk_drift(tmp_path: Path) -> None:
    v1 = write_run(tmp_path / "v1", pass_rate=1.0, by_risk_level={"High": {"passed": 9, "total": 10, "pass_rate": 0.9}})
    v2 = write_run(tmp_path / "v2", pass_rate=1.0, by_risk_level={" CRITICAL ": {"passed": 5, "total": 10, "pass_rate": 0.5}})
    mod = write_json(tmp_path / "mod.json", {"expected_impact": {"fixed_failures": ["r1"]}})
    spec = tmp_path / "loop.yaml"
    spec.write_text(
        f"evolution_loop:\n  id: risk-drift\n  steps:\n    - iteration: 1\n      input_run: {v1}\n      candidate_run: {v1}\n      modification: {mod}\n      decision: accepted\n    - iteration: 2\n      input_run: {v1}\n      candidate_run: {v2}\n      modification: {mod}\n      decision: accepted\n",
        encoding="utf-8",
    )

    report = analyze_evolution_loop(spec)

    assert "high_risk_pass_rate_drifted_down" in report["drift_flags"]
    assert report["risk_level"] == "critical"


def test_evolution_loop_flags_regressions_and_token_drift(tmp_path: Path) -> None:
    v1 = write_run(tmp_path / "v1", pass_rate=1.0)
    v2 = write_run(tmp_path / "v2", pass_rate=0.8)
    v3 = write_run(tmp_path / "v3", pass_rate=0.7)
    mod = write_json(tmp_path / "mod.json", {"expected_impact": {"fixed_failures": ["r1"]}})
    spec = tmp_path / "loop.yaml"
    spec.write_text(
        f"evolution_loop:\n  id: drift\n  steps:\n    - iteration: 1\n      input_run: {v1}\n      candidate_run: {v2}\n      modification: {mod}\n      decision: accepted\n      introduced_regressions: [new-risk]\n    - iteration: 2\n      input_run: {v2}\n      candidate_run: {v3}\n      modification: {mod}\n      decision: accepted\n",
        encoding="utf-8",
    )

    report = analyze_evolution_loop(spec)

    assert report["monotonicity"]["pass_rate_non_decreasing"] is False
    assert "pass_rate_regressed_during_loop" in report["drift_flags"]
    assert "accepted_step_introduced_regressions" in report["drift_flags"]
    assert report["risk_level"] == "high"
    assert {item["flag"] for item in report["risk_evidence"]} >= {"pass_rate_regressed_during_loop", "accepted_step_introduced_regressions"}
