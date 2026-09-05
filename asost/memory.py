"""Atomic JSON checkpoint storage."""
from __future__ import annotations
import json
from pathlib import Path
from threading import Lock


class JSONMemory:
    def __init__(self, path):
        self.path = Path(path)
        self._lock = Lock()

    def read(self, key, default=None):
        with self._lock:
            return self._load().get(key, default)

    def write(self, key, value):
        with self._lock:
            data = self._load()
            data[key] = value
            self.path.parent.mkdir(parents=True, exist_ok=True)
            temporary = self.path.with_suffix(self.path.suffix + ".tmp")
            temporary.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
            temporary.replace(self.path)

    def _load(self):
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
            return data if isinstance(data, dict) else {}
        except (FileNotFoundError, OSError, ValueError):
            return {}
