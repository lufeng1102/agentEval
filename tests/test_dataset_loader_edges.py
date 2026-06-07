from pathlib import Path

import pytest

from config import load_dataset, load_yaml


def test_load_dataset_rejects_recursive_include(tmp_path: Path) -> None:
    dataset = tmp_path / "dataset.yaml"
    dataset.write_text(
        """
includes:
  - dataset.yaml
cases:
  - id: c1
    input: q
""".strip(),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="recursive dataset include"):
        load_dataset(dataset)


def test_load_dataset_rejects_include_glob_with_no_matches(tmp_path: Path) -> None:
    dataset = tmp_path / "dataset.yaml"
    dataset.write_text(
        """
includes:
  - missing/*.yaml
cases:
  - id: c1
    input: q
""".strip(),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="dataset include matched no files: missing/\\*.yaml"):
        load_dataset(dataset)


def test_load_yaml_rejects_non_object_document(tmp_path: Path) -> None:
    dataset = tmp_path / "dataset.yaml"
    dataset.write_text("- not\n- an\n- object\n", encoding="utf-8")

    with pytest.raises(ValueError, match="YAML file must contain an object"):
        load_yaml(dataset)


def test_load_dataset_empty_directory_has_no_cases(tmp_path: Path) -> None:
    dataset = load_dataset(tmp_path)

    assert dataset.cases == []
    assert dataset.metadata == {}


def test_load_dataset_merges_metadata_and_dedupes_sources(tmp_path: Path) -> None:
    (tmp_path / "a.yaml").write_text(
        """
metadata:
  name: first
  sources: [shared, only-a]
cases:
  - id: a
    input: qa
""".strip(),
        encoding="utf-8",
    )
    (tmp_path / "b.yaml").write_text(
        """
metadata:
  name: second
  sources: [shared, only-b]
cases:
  - id: b
    input: qb
""".strip(),
        encoding="utf-8",
    )

    dataset = load_dataset(tmp_path)

    assert dataset.metadata["name"] == "second"
    assert dataset.metadata["sources"] == ["shared", "only-a", str(tmp_path / "a.yaml"), "only-b", str(tmp_path / "b.yaml")]


def test_load_dataset_raises_for_missing_expected_file(tmp_path: Path) -> None:
    dataset = tmp_path / "dataset.yaml"
    dataset.write_text(
        """
cases:
  - id: c1
    input: q
    expected:
      answer_file: missing.txt
""".strip(),
        encoding="utf-8",
    )

    with pytest.raises(FileNotFoundError):
        load_dataset(dataset)
