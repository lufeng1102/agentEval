import json
from pathlib import Path

from config import load_config
from manifest import build_manifest, file_sha256, write_manifest


def test_file_sha256_and_manifest(tmp_path: Path) -> None:
    dataset = tmp_path / "dataset.yaml"
    config_path = Path("examples/configs/static_eval.yaml")
    dataset.write_text("cases: []\n", encoding="utf-8")
    config = load_config(config_path)

    manifest = build_manifest(dataset, config_path, config)
    out = tmp_path / "manifest.json"
    write_manifest(out, manifest)

    payload = json.loads(out.read_text(encoding="utf-8"))
    assert payload["dataset_hash"] == file_sha256(dataset)
    assert payload["config_hash"] == file_sha256(config_path)
    assert payload["runner"]["repeats"] >= 1
    assert payload["prompt_hash"]
