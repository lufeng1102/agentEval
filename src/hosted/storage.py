from __future__ import annotations

import hashlib
import json
import shutil
from pathlib import Path
from typing import Any

from hosted.models import HostedRun, RunArtifact


class LocalHostedStorage:
    def __init__(self, root: str | Path):
        self.root = Path(root)
        self.artifacts_dir = self.root / "artifacts"
        self.runs_dir = self.root / "runs"
        self.root.mkdir(parents=True, exist_ok=True)
        self.artifacts_dir.mkdir(parents=True, exist_ok=True)
        self.runs_dir.mkdir(parents=True, exist_ok=True)

    def get_run_by_key(self, project_id: str, run_key: str) -> HostedRun | None:
        for path in self.runs_dir.glob("*.json"):
            run = HostedRun.model_validate(json.loads(path.read_text(encoding="utf-8")))
            if run.project_id == project_id and run.run_key == run_key:
                return run
        return None

    def get_run(self, run_id: str) -> HostedRun | None:
        path = self.runs_dir / f"{run_id}.json"
        if not path.exists():
            return None
        return HostedRun.model_validate(json.loads(path.read_text(encoding="utf-8")))

    def save_run(self, run: HostedRun) -> None:
        path = self.runs_dir / f"{run.id}.json"
        path.write_text(run.model_dump_json(indent=2), encoding="utf-8")

    def store_artifact(self, run_id: str, source: str | Path, *, kind: str, path_name: str | None = None, content_type: str = "application/octet-stream") -> RunArtifact:
        source_path = Path(source)
        digest = sha256_file(source_path)
        destination_dir = self.artifacts_dir / run_id
        destination_dir.mkdir(parents=True, exist_ok=True)
        name = path_name or source_path.name
        destination = destination_dir / name
        shutil.copyfile(source_path, destination)
        return RunArtifact(
            id=f"artifact_{run_id}_{kind}_{digest[:12]}",
            run_id=run_id,
            kind=kind,
            path=name,
            content_type=content_type,
            size_bytes=destination.stat().st_size,
            sha256=digest,
            storage_path=str(destination),
        )


def sha256_file(path: str | Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def sha256_parts(paths: list[str | Path]) -> str:
    digest = hashlib.sha256()
    for path in paths:
        file_path = Path(path)
        digest.update(file_path.name.encode("utf-8"))
        digest.update(sha256_file(file_path).encode("utf-8"))
    return digest.hexdigest()


def read_json(path: str | Path) -> dict[str, Any]:
    return json.loads(Path(path).read_text(encoding="utf-8"))
