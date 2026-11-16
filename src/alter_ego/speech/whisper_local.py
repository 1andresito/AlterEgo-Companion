"""Local, offline speech recognition with faster-whisper (OpenAI's Whisper on CTranslate2).

The package is optional: it is imported only when first needed, so the rest of
Alter Ego runs without it. The first use downloads the chosen model from
Hugging Face into the usual Hugging Face cache (~/.cache/huggingface); after
that everything stays on this computer.
"""

from __future__ import annotations

import threading

from .audio import AudioClip
from .transcriber import Transcriber, TranscriptionError

# Sizes faster-whisper knows. Bigger is more accurate and slower; ".en" ones are English only.
MODELS = ["tiny", "base", "small", "medium", "large-v3", "tiny.en", "base.en", "small.en"]
DEFAULT_MODEL = "base"
NO_SPEECH_LIMIT = 0.6
INSTALL_HINT = "Install it with:  pip install faster-whisper  (or: pip install -r requirements.txt)"


class WhisperTranscriber(Transcriber):
    id = "whisper"
    label = "Local Whisper (offline, faster-whisper)"

    def __init__(
        self,
        model_name: str = DEFAULT_MODEL,
        language: str = "",
        vad_filter: bool = True,
        beam_size: int = 1,
        prompt: str = "",
    ):
        self._model_name = model_name or DEFAULT_MODEL
        self._language = language.strip() or None
        # Whisper's own silence filter; off when the caller already cut the clip to speech.
        self._vad_filter = vad_filter
        # 1 = greedy and fastest; 5 = more careful, worth it for short clips such as a wake phrase.
        self._beam_size = max(1, beam_size)
        # Words the model should expect, e.g. the character's name, so it spells them right.
        self._prompt = prompt.strip() or None
        self._model = None
        self._lock = threading.Lock()

    @property
    def model_name(self) -> str:
        return self._model_name

    def describe(self) -> str:
        language = self._language or "auto-detect"
        return f"local Whisper '{self._model_name}' ({language})"

    @property
    def ready(self) -> bool:
        return self._model is not None

    def prepare(self) -> str:
        self._load()
        return f"The speech model '{self._model_name}' is loaded and ready."

    def transcribe(self, clip: AudioClip) -> str:
        model = self._load()
        import numpy as np  # A dependency of faster-whisper, so present once _load() succeeded.

        audio = np.asarray(clip.samples, dtype=np.float32)
        try:
            segments, _info = model.transcribe(
                audio,
                language=self._language,
                beam_size=self._beam_size,
                vad_filter=self._vad_filter,
                initial_prompt=self._prompt,
                condition_on_previous_text=False,  # each clip stands alone
            )
            # Segments the model itself thinks are not speech are usually hallucinations.
            return " ".join(
                segment.text.strip() for segment in segments if segment.no_speech_prob < NO_SPEECH_LIMIT
            ).strip()
        except Exception as error:  # noqa: BLE001 - whatever CTranslate2 raises, the app must survive
            raise TranscriptionError(f"The speech model failed: {type(error).__name__}: {error}") from None

    def _load(self):
        with self._lock:
            if self._model is not None:
                return self._model
            try:
                from faster_whisper import WhisperModel
            except ImportError:
                raise TranscriptionError(
                    f"I can't listen yet: the speech recognition package is missing. {INSTALL_HINT}"
                ) from None
            try:
                self._model = WhisperModel(self._model_name, device="cpu", compute_type="int8")
            except Exception as error:  # noqa: BLE001 - download/loading errors come in many types
                raise TranscriptionError(
                    f"I couldn't load the speech model '{self._model_name}': {error}. "
                    "The first use needs an internet connection to download it."
                ) from None
            return self._model
