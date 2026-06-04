from pathlib import Path

import pytest
from pydantic import ValidationError

from config import load_dataset
from schemas import EvalCase


def test_load_dataset_parses_cases() -> None:
    dataset = load_dataset(Path("examples/datasets/basic_agent_eval.yaml"))

    assert len(dataset.cases) == 6
    assert dataset.cases[0].id == "factual_001"
    assert "factuality" in dataset.cases[0].tags


def test_eval_case_requires_input() -> None:
    with pytest.raises(ValidationError):
        EvalCase(id="bad", input="")
