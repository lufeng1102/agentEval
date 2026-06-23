from __future__ import annotations

import threading
from pathlib import Path

from schemas import AgentTrace


class AppendJsonlTraceWriter:
    def __init__(self, path: str | Path):
        self.path = Path(path)
        self._lock = threading.Lock()

    def append(self, trace: AgentTrace) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        line = trace.model_dump_json()
        with self._lock:
            with self.path.open("a", encoding="utf-8") as handle:
                handle.write(line + "\n")
