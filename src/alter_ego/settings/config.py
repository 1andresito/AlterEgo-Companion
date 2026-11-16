"""Loads and saves the user's configuration (AI provider, model, URLs, keys).

The file is plain JSON. It is created on first save, and it lives outside the
repository so API keys and personal settings never end up in Git:

- running from source:   <project>/data/config.json   (data/ is gitignored)
- packaged (PyInstaller): %APPDATA%/AlterEgo/config.json on Windows,
                          ~/.config/alter_ego/config.json elsewhere
- override either with the ALTER_EGO_DATA_DIR environment variable.
"""

from __future__ import annotations

import copy
import json
import os
import sys
from pathlib import Path
from typing import Any

CONFIG_FILENAME = "config.json"

DEFAULTS: dict[str, Any] = {
    "provider": "ollama",
    "ollama": {
        "base_url": "http://localhost:11434",
        "model": "",  # empty = use the first model Ollama reports
    },
    "claude_code": {
        "command": "claude",  # or a full path to the Claude Code executable
        "model": "",          # "", "default", "opus", "sonnet" or "haiku"
        "effort": "",         # "", "low", "medium" or "high": lower is faster
    },
    "openai": {
        "base_url": "https://api.openai.com/v1",  # or Groq, OpenRouter, LM Studio, ...
        "api_key": "",                            # or set the OPENAI_API_KEY environment variable
        "model": "",
    },
    "memory": {
        "enabled": True,         # save conversations to data/memory.db and restore them on start
        "context_messages": 30,  # how many recent messages the AI sees; 0 = all of them
    },
}


def data_dir() -> Path:
    override = os.environ.get("ALTER_EGO_DATA_DIR")
    if override:
        return Path(override)
    if getattr(sys, "frozen", False):
        if sys.platform == "win32":
            base = Path(os.environ.get("APPDATA", Path.home()))
            return base / "AlterEgo"
        return Path.home() / ".config" / "alter_ego"
    # src/alter_ego/settings/config.py -> project root is three folders up.
    return Path(__file__).resolve().parents[3] / "data"


class Config:
    """A small wrapper around a dict with sections, e.g. config.get("ollama", "model")."""

    def __init__(self, path: Path, data: dict[str, Any] | None = None):
        self.path = path
        self._data: dict[str, Any] = copy.deepcopy(DEFAULTS)
        if data:
            self._merge(data)

    @classmethod
    def load(cls, path: Path | None = None) -> Config:
        path = path or data_dir() / CONFIG_FILENAME
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(raw, dict):
                raise ValueError("top level must be a JSON object")
        except FileNotFoundError:
            raw = {}
        except (OSError, ValueError) as error:
            print(f"Warning: could not read {path}: {error}. Using default settings.")
            raw = {}
        return cls(path, raw)

    def save(self) -> None:
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self.path.write_text(json.dumps(self._data, indent=2) + "\n", encoding="utf-8")
        except OSError as error:
            print(f"Warning: could not save settings to {self.path}: {error}")

    def _merge(self, data: dict[str, Any]) -> None:
        # Unknown keys are kept, so future providers can store their own section.
        for key, value in data.items():
            if isinstance(value, dict) and isinstance(self._data.get(key), dict):
                self._data[key].update(value)
            else:
                self._data[key] = value

    # ----- Accessors -----

    @property
    def provider(self) -> str:
        return str(self._data.get("provider", DEFAULTS["provider"]))

    @provider.setter
    def provider(self, provider_id: str) -> None:
        self._data["provider"] = provider_id

    @property
    def memory_enabled(self) -> bool:
        return bool(self.get("memory", "enabled", True))

    def get(self, section: str, key: str, default: Any = None) -> Any:
        values = self._data.get(section)
        if isinstance(values, dict):
            return values.get(key, default)
        return default

    def set(self, section: str, key: str, value: Any) -> None:
        self._data.setdefault(section, {})[key] = value
