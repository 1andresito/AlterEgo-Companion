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
        "model": "",               # empty = use the first model Ollama reports
        "command": "ollama",       # or a full path to the Ollama executable
        "auto_start": True,        # run `ollama serve` when nothing answers at a local base_url; stopped again on quit
        "auto_pull": True,         # download default_model before the first reply if no model is installed
        "default_model": "llama3.2",
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
    "speech": {
        "enabled": True,                # push to talk: hold the key (or the chat's talk button) to speak
        "push_to_talk_key": "F9",       # see Voice -> Key in the menu for the names
        "microphone": "",               # "" = system default, otherwise a device name from Voice -> Microphone
        "transcriber": "whisper",       # "whisper" = local and offline, "openai" = the API from the openai section
        "whisper_model": "base",        # tiny, base, small, medium, large-v3, or an English-only ".en" variant
        "openai_model": "whisper-1",    # the API's speech model (Groq: whisper-large-v3)
        "language": "",                 # "" = detect automatically, or a code such as "en", "es", "ja"
        "review_before_sending": False, # True = put the text in the input box instead of sending it at once
        "hands_free": False,            # keep the microphone open and wake up on the wake phrase (opt-in)
        "wake_phrase": "hey alter ego",
        "wake_model": "tiny",           # the small Whisper model that listens for the wake phrase
        "wake_sensitivity": "normal",   # "low", "normal" or "high": how quiet speech may be and still be noticed
        "awake_seconds": 3,             # seconds of silence after the wake phrase before it stops listening
        "follow_up_seconds": 3,         # seconds of silence after a reply before it stops listening; 0 = none
    },
    "voice": {
        "enabled": True,                # speak replies out loud (the voice files are downloaded on request, not silently)
        "synthesizer": "kokoro",        # "kokoro" = local and offline, "openai" = the API from the openai section
        "kokoro_voice": "alter_ego",    # "alter_ego" (the soft blend) or a Kokoro voice id such as "af_heart"
        "kokoro_model": "standard",     # "standard" (310 MB) or "small" (88 MB, a little faster and rougher)
        "openai_model": "tts-1",        # the API's speech model
        "openai_voice": "nova",         # the API's voice name
        "pitch": 2,                     # semitones above the Kokoro voice's natural pitch (negative = lower); Kokoro only
        "speed": 1.0,                   # tempo: 0.8 slower ... 1.2 faster
        "volume": 0.8,                  # 0.0 .. 1.0
        "crt_effect": True,             # a light "speaking from inside a monitor" tone
        "speaker": "",                  # "" = system default output, otherwise a device name from the menu
        "models_dir": "",               # "" = data/voices; where the Kokoro files are kept
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

    @property
    def speech_enabled(self) -> bool:
        return bool(self.get("speech", "enabled", True))

    @property
    def voice_enabled(self) -> bool:
        return bool(self.get("voice", "enabled", True))

    @property
    def hands_free_enabled(self) -> bool:
        return self.speech_enabled and bool(self.get("speech", "hands_free", False))

    def get(self, section: str, key: str, default: Any = None) -> Any:
        values = self._data.get(section)
        if isinstance(values, dict):
            return values.get(key, default)
        return default

    def set(self, section: str, key: str, value: Any) -> None:
        self._data.setdefault(section, {})[key] = value
