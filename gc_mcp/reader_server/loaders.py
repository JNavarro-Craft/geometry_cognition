from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any


DEFAULT_OUTPUTS_DIR = r"C:\geometry_cognition\outputs"


def structured_file_not_found(filename: str) -> dict[str, str]:
    return {
        "error": "file_not_found",
        "file": filename,
        "hint": "run pipeline first",
    }


@dataclass
class _CacheEntry:
    mtime: float
    data: Any


class OutputsLoader:
    """
    Read-only JSON loader with mtime-based cache.
    Designed for future extension to multi-session outputs by swapping path resolution.
    """

    def __init__(self, outputs_dir: Path | None = None) -> None:
        env_dir = os.environ.get("GC_OUTPUTS_DIR", "").strip()
        self.outputs_dir = outputs_dir or Path(env_dir or DEFAULT_OUTPUTS_DIR)
        self._cache: dict[str, _CacheEntry] = {}

    def _path(self, filename: str) -> Path:
        return self.outputs_dir / filename

    def load_json(self, filename: str) -> tuple[Any | None, dict[str, str] | None]:
        path = self._path(filename)
        if not path.exists():
            return None, structured_file_not_found(filename)
        stat = path.stat()
        cached = self._cache.get(filename)
        if cached and cached.mtime == stat.st_mtime:
            return cached.data, None
        with path.open("r", encoding="utf-8") as f:
            data = json.load(f)
        self._cache[filename] = _CacheEntry(mtime=stat.st_mtime, data=data)
        return data, None

    def load_first_available(self, filenames: list[str]) -> tuple[Any | None, dict[str, str] | None, str | None]:
        for name in filenames:
            data, err = self.load_json(name)
            if err is None:
                return data, None, name
        return None, structured_file_not_found(filenames[0]), None

    def invalidate(self, filenames: list[str] | None = None) -> None:
        if filenames is None:
            self._cache.clear()
            return
        for name in filenames:
            self._cache.pop(name, None)

