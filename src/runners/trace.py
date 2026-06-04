from __future__ import annotations

import json
from pathlib import Path
from typing import Iterable

from pydantic import BaseModel


class JsonlTraceWriter:
    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def write(self, records: Iterable[BaseModel]) -> None:
        with self.path.open("w", encoding="utf-8") as file:
            for record in records:
                file.write(json.dumps(record.model_dump(mode="json"), ensure_ascii=False) + "\n")
