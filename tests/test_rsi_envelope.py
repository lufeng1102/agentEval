from pathlib import Path

from rsi.envelope import check_envelope
from tests.rsi_helpers import write_json


def test_envelope_accepts_safe_modification_and_rejects_forbidden(tmp_path: Path) -> None:
    policy = tmp_path / "policy.yaml"
    policy.write_text(
        """
safety_envelope:
  forbidden_modifications: [safety_policy, evaluator_thresholds]
  required_invariants: [safety_policy_not_relaxed]
  forbidden_actions: [delete_regression]
""".strip(),
        encoding="utf-8",
    )
    safe = write_json(tmp_path / "safe.json", {"modified_components": ["prompt"], "rollback_plan": "restore"})
    unsafe = write_json(tmp_path / "unsafe.json", {"modified_components": ["safety_policy"], "actions": [{"type": "delete_regression"}]})

    assert check_envelope(safe, policy)["accepted"] is True
    rejected = check_envelope(unsafe, policy)
    assert rejected["accepted"] is False
    assert {item["type"] for item in rejected["violations"]} >= {"forbidden_modification", "forbidden_action"}
