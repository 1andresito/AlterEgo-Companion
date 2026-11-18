"""Voice output (v0.6.0): text-to-speech engines, a player and the Speaker controller.

Mirrors the speech package: every engine implements the Synthesizer interface
in synthesizer.py, and the rest of the app only talks to that.

Alter Ego has one voice, and it is not a setting: the owner's RVC model
shipped in assets/voice/, which Kokoro's speech is converted to. If that
file is missing (a checkout without Git LFS), the soft Kokoro blend speaks
so the app is never mute. Neither the
menus nor config.json can choose another voice, pitch or speed; only
whether to speak, how loud, and through which speakers.
"""

from __future__ import annotations

from pathlib import Path

from ..settings.config import Config, assets_dir, data_dir
from .kokoro_local import KokoroSynthesizer
from .player import SpeechPlayer
from .rvc_local import CHARACTER_DIR, CharacterVoiceSynthesizer, find_character_model
from .speaker import Speaker, SpeakingState, VoiceStyle
from .synthesizer import Speech, SynthesisError, Synthesizer

MODELS_SUBDIR = "voices"
RVC_SUBDIR = "rvc"  # The RVC base models (pitch tracker and speech encoder) shared by any voice model.


def models_dir(config: Config) -> Path:
    custom = str(config.get("voice", "models_dir", "") or "")
    return Path(custom) if custom else data_dir() / MODELS_SUBDIR


def character_dir() -> Path:
    """Where the one voice model ships: assets/voice/ in the project."""
    return assets_dir() / CHARACTER_DIR


def character_model(folder: Path | None = None) -> Path | None:
    """The shipped voice model, or None if it is missing; `folder` exists for the tests."""
    return find_character_model(folder if folder is not None else character_dir())


def synthesizer_signature(config: Config, voice_folder: Path | None = None) -> tuple:
    """Everything build_synthesizer reads: equal signatures mean the loaded voice (43 s to load) can be kept."""
    return (config.voice_enabled, str(models_dir(config)), str(character_model(voice_folder)))


def build_synthesizer(config: Config, voice_folder: Path | None = None) -> Synthesizer | None:
    """Alter Ego's voice, or None when spoken replies are switched off."""
    if not config.voice_enabled:
        return None
    kokoro = KokoroSynthesizer(models_dir=models_dir(config))  # Always the soft blend, standard model.
    model = character_model(voice_folder)
    if model is None:
        return kokoro
    return CharacterVoiceSynthesizer(kokoro, model_path=model, models_dir=models_dir(config) / RVC_SUBDIR)


def build_voice(config: Config) -> Synthesizer | None:
    """The voice as the app uses it: build_synthesizer's engine, run in a helper process
    (voice/remote.py), so its 2-3 GB can be given back. None when spoken replies are off."""
    local = build_synthesizer(config)
    if local is None:
        return None
    from ..core import gpu_pack
    from .remote import RemoteVoice

    return RemoteVoice(local, gpu_site=lambda: gpu_pack.site_dir() if gpu_pack.installed() else None)


__all__ = [
    "CharacterVoiceSynthesizer",
    "synthesizer_signature",
    "KokoroSynthesizer",
    "Speaker",
    "SpeakingState",
    "Speech",
    "SpeechPlayer",
    "SynthesisError",
    "Synthesizer",
    "VoiceStyle",
    "build_synthesizer",
    "build_voice",
    "character_dir",
    "character_model",
    "models_dir",
]
