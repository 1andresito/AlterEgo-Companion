"""Voice output (v0.6.0): text-to-speech engines, a player and the Speaker controller.

Mirrors the speech package: every engine implements the Synthesizer interface
in synthesizer.py, and the rest of the app only talks to that.
"""

from __future__ import annotations

from pathlib import Path

from ..settings.config import Config, data_dir
from .kokoro_local import KokoroSynthesizer
from .openai_tts import OpenAISynthesizer
from .player import SpeechPlayer
from .speaker import DEFAULT_PITCH_SEMITONES, DEFAULT_SPEED, Speaker, SpeakingState, VoiceStyle
from .synthesizer import Speech, SynthesisError, Synthesizer

# synthesizer id -> label shown in menus.
SYNTHESIZER_LABELS: dict[str, str] = {
    KokoroSynthesizer.id: KokoroSynthesizer.label,
    OpenAISynthesizer.id: OpenAISynthesizer.label,
}

MODELS_SUBDIR = "voices"


def models_dir(config: Config) -> Path:
    custom = str(config.get("voice", "models_dir", "") or "")
    return Path(custom) if custom else data_dir() / MODELS_SUBDIR


def build_synthesizer(config: Config) -> Synthesizer | None:
    """The speech engine the settings ask for, or None when spoken replies are switched off."""
    if not config.voice_enabled:
        return None
    kind = str(config.get("voice", "synthesizer", KokoroSynthesizer.id) or KokoroSynthesizer.id)
    if kind == OpenAISynthesizer.id:
        return OpenAISynthesizer(
            base_url=str(config.get("openai", "base_url", "") or ""),
            api_key=str(config.get("openai", "api_key", "") or ""),
            model=str(config.get("voice", "openai_model", "") or ""),
            voice=str(config.get("voice", "openai_voice", "") or ""),
        )
    if kind != KokoroSynthesizer.id:
        print(f"Warning: unknown voice synthesizer '{kind}' in settings. Using local Kokoro.")
    return KokoroSynthesizer(
        voice=str(config.get("voice", "kokoro_voice", "") or ""),
        model=str(config.get("voice", "kokoro_model", "") or ""),
        models_dir=models_dir(config),
    )


def build_style(config: Config) -> VoiceStyle:
    def number(key: str, default: float) -> float:
        try:
            return float(config.get("voice", key, default))
        except (TypeError, ValueError):
            return default

    return VoiceStyle(
        pitch_semitones=number("pitch", DEFAULT_PITCH_SEMITONES),
        speed=number("speed", DEFAULT_SPEED),
        crt_effect=bool(config.get("voice", "crt_effect", True)),
    )


__all__ = [
    "KokoroSynthesizer",
    "OpenAISynthesizer",
    "SYNTHESIZER_LABELS",
    "Speaker",
    "SpeakingState",
    "Speech",
    "SpeechPlayer",
    "SynthesisError",
    "Synthesizer",
    "VoiceStyle",
    "build_style",
    "build_synthesizer",
    "models_dir",
]
