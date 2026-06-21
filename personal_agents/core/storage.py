from __future__ import annotations

import json
from pathlib import Path
from typing import Any


class JsonStore:
    """Tiny JSON-file persistence helper: load with a default, save atomically.

    Human-readable on disk so you can open an agent's memory and read it.
    """

    def __init__(self, path: Path):
        self.path = Path(path)

    def load(self, default: Any = None) -> Any:
        if not self.path.exists():
            return default
        with self.path.open("r", encoding="utf-8") as f:
            return json.load(f)

    def save(self, data: Any) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_name(self.path.name + ".tmp")
        with tmp.open("w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        tmp.replace(self.path)  # atomic on the same filesystem
