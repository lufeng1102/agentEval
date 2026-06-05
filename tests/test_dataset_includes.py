from pathlib import Path

from config import load_dataset


def test_load_dataset_resolves_expected_files(tmp_path: Path) -> None:
    (tmp_path / "answer.txt").write_text("H2O\n", encoding="utf-8")
    (tmp_path / "schema.json").write_text('{"type":"object","required":["answer"]}', encoding="utf-8")
    dataset_file = tmp_path / "dataset.yaml"
    dataset_file.write_text(
        """
cases:
  - id: c1
    input: q
    expected:
      answer_file: answer.txt
      json_schema_file: schema.json
""".strip(),
        encoding="utf-8",
    )

    dataset = load_dataset(dataset_file)

    assert dataset.cases[0].expected["answer"] == "H2O"
    assert dataset.cases[0].expected["json_schema"] == {"type": "object", "required": ["answer"]}


def test_load_dataset_directory_merges_yaml_files(tmp_path: Path) -> None:
    (tmp_path / "a.yaml").write_text(
        """
metadata:
  name: a
cases:
  - id: a1
    input: q1
""".strip(),
        encoding="utf-8",
    )
    (tmp_path / "b.yaml").write_text(
        """
cases:
  - id: b1
    input: q2
""".strip(),
        encoding="utf-8",
    )

    dataset = load_dataset(tmp_path)

    assert [case.id for case in dataset.cases] == ["a1", "b1"]
    assert dataset.metadata["sources"] == [str(tmp_path / "a.yaml"), str(tmp_path / "b.yaml")]


def test_load_dataset_includes_relative_globs(tmp_path: Path) -> None:
    cases_dir = tmp_path / "cases"
    cases_dir.mkdir()
    (cases_dir / "one.yaml").write_text("cases:\n  - id: c1\n    input: q1\n", encoding="utf-8")
    (cases_dir / "two.yaml").write_text("cases:\n  - id: c2\n    input: q2\n", encoding="utf-8")
    root = tmp_path / "dataset.yaml"
    root.write_text(
        """
metadata:
  name: combined
includes:
  - cases/*.yaml
cases:
  - id: root
    input: q0
""".strip(),
        encoding="utf-8",
    )

    dataset = load_dataset(root)

    assert [case.id for case in dataset.cases] == ["root", "c1", "c2"]
    assert dataset.metadata["name"] == "combined"


def test_load_dataset_rejects_duplicate_case_ids(tmp_path: Path) -> None:
    (tmp_path / "a.yaml").write_text("cases:\n  - id: dup\n    input: q1\n", encoding="utf-8")
    (tmp_path / "b.yaml").write_text("cases:\n  - id: dup\n    input: q2\n", encoding="utf-8")

    try:
        load_dataset(tmp_path)
    except ValueError as exc:
        assert "duplicate case id: dup" in str(exc)
    else:
        raise AssertionError("expected duplicate case id failure")
