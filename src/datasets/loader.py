from __future__ import annotations

from pathlib import Path

from config import load_dataset
from schemas import EvalDataset


class DatasetLoader:
    def load(self, path: str | Path) -> EvalDataset:
        return load_dataset(path)
