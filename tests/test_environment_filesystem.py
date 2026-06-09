from pathlib import Path

from config import EnvironmentConfig
from environments.filesystem import diff_snapshots, prepare_filesystem_environment, snapshot_directory
from schemas import EvalCase


def test_filesystem_environment_copies_fixture_and_snapshots(tmp_path: Path) -> None:
    fixture = tmp_path / "fixture"
    (fixture / "src").mkdir(parents=True)
    (fixture / "src" / "auth.py").write_text("old", encoding="utf-8")

    prepared = prepare_filesystem_environment(EvalCase(id="case/1", input="fix"), 0, tmp_path / "run", EnvironmentConfig(type="filesystem", fixture=fixture))

    assert (prepared.root / "src" / "auth.py").read_text(encoding="utf-8") == "old"
    assert "src/auth.py" in prepared.record.before.files


def test_filesystem_environment_detects_created_modified_deleted_and_protected(tmp_path: Path) -> None:
    root = tmp_path / "workspace"
    (root / "src").mkdir(parents=True)
    (root / "tests").mkdir(parents=True)
    (root / "src" / "auth.py").write_text("old", encoding="utf-8")
    (root / "src" / "delete.py").write_text("remove", encoding="utf-8")
    before = snapshot_directory(root, ["**/*"], [])

    (root / "src" / "auth.py").write_text("new", encoding="utf-8")
    (root / "src" / "delete.py").unlink()
    (root / "tests" / "hidden.txt").write_text("tamper", encoding="utf-8")
    after = snapshot_directory(root, ["**/*"], [])
    diff = diff_snapshots(before, after, ["tests/**"])

    assert diff.modified == ["src/auth.py"]
    assert diff.deleted == ["src/delete.py"]
    assert diff.created == ["tests/hidden.txt"]
    assert diff.protected_path_violations == ["tests/hidden.txt"]
