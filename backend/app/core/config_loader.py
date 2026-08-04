"""Configuration loader — all game content is data-driven JSON."""

from __future__ import annotations

import json
import threading
from pathlib import Path
from typing import Any

# Resolve repo root: backend/app/core -> ../../../
ROOT = Path(__file__).resolve().parents[3]
CONFIG_DIR = ROOT / "data" / "configs"
SAVES_DIR = ROOT / "saves"


class ConfigRegistry:
    """Thread-safe lazy registry for all JSON configs.

    New config files dropped into data/configs/ are pickable via load(name).
    Systems should depend on this registry rather than hard-coded paths.
    """

    _instance: ConfigRegistry | None = None
    _lock = threading.Lock()

    def __init__(self, config_dir: Path | None = None) -> None:
        self.config_dir = config_dir or CONFIG_DIR
        self._cache: dict[str, Any] = {}
        self._file_mtimes: dict[str, float] = {}

    @classmethod
    def instance(cls) -> ConfigRegistry:
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = cls()
        return cls._instance

    @classmethod
    def reset(cls) -> None:
        with cls._lock:
            cls._instance = None

    def _path(self, name: str) -> Path:
        if not name.endswith(".json"):
            name = f"{name}.json"
        return self.config_dir / name

    def load(self, name: str, *, force: bool = False) -> Any:
        path = self._path(name)
        key = path.stem
        if not path.exists():
            raise FileNotFoundError(f"Config not found: {path}")
        mtime = path.stat().st_mtime
        if not force and key in self._cache and self._file_mtimes.get(key) == mtime:
            return self._cache[key]
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        self._cache[key] = data
        self._file_mtimes[key] = mtime
        return data

    def get(self, name: str, *keys: str, default: Any = None) -> Any:
        data = self.load(name)
        cur: Any = data
        for k in keys:
            if not isinstance(cur, dict) or k not in cur:
                return default
            cur = cur[k]
        return cur

    def list_configs(self) -> list[str]:
        return sorted(p.stem for p in self.config_dir.glob("*.json"))

    def reload_all(self) -> list[str]:
        names = self.list_configs()
        for n in names:
            self.load(n, force=True)
        return names


def get_configs() -> ConfigRegistry:
    return ConfigRegistry.instance()
