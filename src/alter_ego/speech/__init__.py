"""Voice input: a microphone recorder, speech-recognition engines and the push-to-talk controller.

Mirrors the providers package: every engine implements the Transcriber
interface in transcriber.py, and the rest of the app only talks to that.
"""

from __future__ import annotations

from ..settings.config import Config
from .audio import AudioClip
from .openai_stt import OpenAITranscriber
from .transcriber import Transcriber, TranscriptionError
from .whisper_local import WhisperTranscriber

# transcriber id -> label shown in menus.
TRANSCRIBER_LABELS: dict[str, str] = {
    WhisperTranscriber.id: WhisperTranscriber.label,
    OpenAITranscriber.id: OpenAITranscriber.label,
}


def build_transcriber(config: Config) -> Transcriber | None:
    """The speech engine the settings ask for, or None when push to talk is switched off."""
    if not config.speech_enabled:
        return None
    language = str(config.get("speech", "language", "") or "")
    kind = str(config.get("speech", "transcriber", WhisperTranscriber.id) or WhisperTranscriber.id)
    if kind == OpenAITranscriber.id:
        return OpenAITranscriber(
            base_url=str(config.get("openai", "base_url", "") or ""),
            api_key=str(config.get("openai", "api_key", "") or ""),
            model=str(config.get("speech", "openai_model", "") or ""),
            language=language,
        )
    if kind != WhisperTranscriber.id:
        print(f"Warning: unknown speech transcriber '{kind}' in settings. Using local Whisper.")
    return WhisperTranscriber(
        model_name=str(config.get("speech", "whisper_model", "") or ""),
        language=language,
    )


def build_wake_transcriber(config: Config, main: Transcriber | None) -> Transcriber | None:
    """The engine that listens for the wake phrase: always local Whisper, small and fast.

    It is tuned differently from the main engine: the language is fixed (auto-detection
    on a one-second clip guesses wrong far too often), the phrase itself is given as a
    vocabulary hint, Whisper's own silence filter is off (our detector already cut the
    clip) and a wider beam is used because the clip is short anyway.
    """
    if not config.hands_free_enabled or main is None:
        return None
    phrase = str(config.get("speech", "wake_phrase", "hey alter ego") or "hey alter ego")
    return WhisperTranscriber(
        model_name=str(config.get("speech", "wake_model", "tiny") or "tiny"),
        language=str(config.get("speech", "language", "") or "en"),
        vad_filter=False,
        beam_size=5,
        prompt=phrase.title() + ".",
    )


__all__ = [
    "AudioClip",
    "OpenAITranscriber",
    "TRANSCRIBER_LABELS",
    "Transcriber",
    "TranscriptionError",
    "WhisperTranscriber",
    "build_transcriber",
    "build_wake_transcriber",
]
