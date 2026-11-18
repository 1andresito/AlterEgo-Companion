"""Local, offline text-to-speech with Kokoro (kokoro-onnx).

Kokoro is a small (82 M parameter), Apache-licensed speech model that sounds
natural and runs comfortably on a CPU. The package is optional: it is imported
only when first needed, so the rest of Alter Ego runs without it.

The model and voice files are not on PyPI. prepare() downloads them once from
the kokoro-onnx GitHub release into the data folder (about 340 MB for the
standard model, 120 MB for the small one); after that everything is offline.

Alter Ego's own voice is a blend of several Kokoro voices, mixed to be soft,
youthful and gentle. The app always uses that blend (as the stand-in voice, or
as the source the character voice converts); the other voice ids remain for
the engine itself and its tests, not as a choice for the user.
"""

from __future__ import annotations

import array
import logging
import os
import threading
import urllib.error
import urllib.request
from pathlib import Path

from ..providers.https import urlopen
from .device import cpu_threads
from .synthesizer import Speech, Synthesizer, SynthesisError

INSTALL_HINT = "Install it with:  pip install kokoro-onnx  (or: pip install -r requirements.txt)"
DOWNLOAD_BASE = "https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0/"
VOICES_FILE = "voices-v1.0.bin"
# Config value -> (file name, approximate size in MB). "standard" is full precision,
# "small" is 8-bit: a little faster and a quarter of the download, slightly rougher.
MODELS: dict[str, tuple[str, int]] = {
    "standard": ("kokoro-v1.0.onnx", 310),
    "small": ("kokoro-v1.0.int8.onnx", 88),
}
DEFAULT_MODEL = "standard"
SAMPLE_RATE = 24000
THREADS = cpu_threads()  # Half the cores: fast enough to speak ahead of playback.

# Alter Ego's voice: the two best-sounding soft American voices, with a little
# of the whispery one for breath and shyness. Weights are relative.
PRESET_VOICE = "alter_ego"
PRESETS: dict[str, dict[str, float]] = {
    PRESET_VOICE: {"af_heart": 0.5, "af_bella": 0.3, "af_nicole": 0.2},
}
DEFAULT_VOICE = PRESET_VOICE

# Kokoro voice id -> description. The first letter is the language
# (a American English, b British English, j Japanese, ...), the second f/m.
VOICES: dict[str, str] = {
    PRESET_VOICE: "Alter Ego (soft blend)",
    "af_heart": "Heart (American, warm)",
    "af_bella": "Bella (American, bright)",
    "af_nicole": "Nicole (American, whispery)",
    "af_sarah": "Sarah (American)",
    "af_sky": "Sky (American)",
    "af_aoede": "Aoede (American)",
    "af_kore": "Kore (American)",
    "af_nova": "Nova (American)",
    "af_jessica": "Jessica (American)",
    "af_river": "River (American)",
    "af_alloy": "Alloy (American)",
    "bf_emma": "Emma (British)",
    "bf_isabella": "Isabella (British)",
    "bf_lily": "Lily (British)",
    "bf_alice": "Alice (British)",
    "am_michael": "Michael (American, male)",
    "am_adam": "Adam (American, male)",
    "am_puck": "Puck (American, male)",
    "bm_george": "George (British, male)",
    "bm_lewis": "Lewis (British, male)",
    "jf_alpha": "Alpha (Japanese)",
    "jf_gongitsune": "Gongitsune (Japanese)",
    "jf_nezumi": "Nezumi (Japanese)",
    "jf_tebukuro": "Tebukuro (Japanese)",
    "jm_kumo": "Kumo (Japanese, male)",
    "ef_dora": "Dora (Spanish)",
    "em_alex": "Alex (Spanish, male)",
    "ff_siwis": "Siwis (French)",
    "if_sara": "Sara (Italian)",
    "im_nicola": "Nicola (Italian, male)",
    "pf_dora": "Dora (Portuguese)",
    "pm_alex": "Alex (Portuguese, male)",
    "zf_xiaoxiao": "Xiaoxiao (Chinese)",
    "zm_yunxi": "Yunxi (Chinese, male)",
    "hf_alpha": "Alpha (Hindi)",
    "hm_omega": "Omega (Hindi, male)",
}
ENGLISH_VOICES = [name for name in VOICES if name == PRESET_VOICE or name[0] in "ab"]
OTHER_VOICES = [name for name in VOICES if name not in ENGLISH_VOICES]

# First letter of a voice id -> the language code espeak needs for its phonemes.
_LANGUAGES = {"a": "en-us", "b": "en-gb", "j": "ja", "z": "cmn", "e": "es", "f": "fr-fr", "h": "hi", "i": "it", "p": "pt-br"}


def voice_language(voice: str) -> str:
    if voice in PRESETS:
        voice = next(iter(PRESETS[voice]))
    return _LANGUAGES.get(voice[:1], "en-us")


class KokoroSynthesizer(Synthesizer):
    id = "kokoro"
    label = "Local Kokoro (offline, kokoro-onnx)"

    def __init__(self, voice: str = DEFAULT_VOICE, model: str = DEFAULT_MODEL, models_dir: Path | str = "."):
        self._voice = voice if voice in VOICES else DEFAULT_VOICE
        if voice not in VOICES:
            print(f"Warning: unknown Kokoro voice '{voice}', using '{DEFAULT_VOICE}'.")
        self._model_key = model if model in MODELS else DEFAULT_MODEL
        self._dir = Path(models_dir)
        self._kokoro = None
        self._style = None  # The blended style vector for the chosen voice.
        self._lock = threading.Lock()

    @property
    def voice(self) -> str:
        return self._voice

    @property
    def model_path(self) -> Path:
        return self._dir / MODELS[self._model_key][0]

    @property
    def voices_path(self) -> Path:
        return self._dir / VOICES_FILE

    @property
    def download_size_mb(self) -> int:
        return MODELS[self._model_key][1] + 28

    def describe(self) -> str:
        return f"local Kokoro voice '{self._voice}' ({self._model_key} model)"

    @property
    def ready(self) -> bool:
        return self._kokoro is not None

    @property
    def needs_download(self) -> bool:
        return not (self.model_path.is_file() and self.voices_path.is_file())

    def download(self) -> None:
        """Fetch the model files if missing, without loading them (voice/remote.py loads them elsewhere)."""
        self._download()

    def prepare(self) -> str:
        downloaded = self.needs_download
        self._download()
        self._load()
        if downloaded:
            return f"My voice is downloaded and ready. Say something and I'll answer out loud."
        return f"My voice ('{self._voice}') is loaded and ready."

    def synthesize(self, text: str, speed: float = 1.0) -> Speech:
        kokoro = self._load()
        text = text.strip()
        if not text:
            return Speech.empty(SAMPLE_RATE)
        speed = max(0.5, min(2.0, float(speed)))  # kokoro-onnx asserts this range
        try:
            audio, rate = kokoro.create(text, voice=self._style, speed=speed, lang=voice_language(self._voice))
        except Exception as error:  # noqa: BLE001 - whatever onnxruntime/espeak raise, the app must survive
            raise SynthesisError(f"My voice failed: {type(error).__name__}: {error}") from None
        samples = array.array("f", audio.astype("float32").tobytes())
        return Speech(samples, int(rate))

    # ----- Files and model -----

    def _download(self) -> None:
        if not self.needs_download:
            return
        self._dir.mkdir(parents=True, exist_ok=True)
        for name in (VOICES_FILE, MODELS[self._model_key][0]):
            target = self._dir / name
            if target.is_file():
                continue
            partial = target.with_suffix(target.suffix + ".part")
            try:
                request = urllib.request.Request(DOWNLOAD_BASE + name, headers={"User-Agent": "AlterEgo-Companion"})
                with urlopen(request, timeout=60) as response, open(partial, "wb") as out:
                    while True:
                        chunk = response.read(1 << 20)
                        if not chunk:
                            break
                        out.write(chunk)
                os.replace(partial, target)
            except (urllib.error.URLError, OSError) as error:
                try:
                    partial.unlink()
                except OSError:
                    pass
                raise SynthesisError(
                    f"I couldn't download my voice ({name}): {getattr(error, 'reason', error)}. "
                    "Check the internet connection and try again from the Spoken replies menu."
                ) from None

    def _load(self):
        with self._lock:
            if self._kokoro is not None:
                return self._kokoro
            try:
                from kokoro_onnx import Kokoro
            except ImportError:
                raise SynthesisError(f"I can't speak yet: the text-to-speech package is missing. {INSTALL_HINT}") from None
            if self.needs_download:
                raise SynthesisError(
                    f"I can't speak yet: my voice isn't downloaded. Choose Spoken replies -> Download my voice "
                    f"(about {self.download_size_mb} MB, once)."
                )
            logging.getLogger("phonemizer").setLevel(logging.ERROR)
            try:
                kokoro = self._open(Kokoro)
                self._style = self._blend(kokoro)
            except Exception as error:  # noqa: BLE001 - loading errors come in many types
                raise SynthesisError(
                    f"I couldn't load my voice: {type(error).__name__}: {error}. "
                    "If the files are damaged, delete them from the data folder and download again."
                ) from None
            self._kokoro = kokoro
            return kokoro

    def _open(self, kokoro_class):
        """Load the model with half the cores, so speaking never takes the whole computer."""
        try:
            import onnxruntime

            options = onnxruntime.SessionOptions()
            options.intra_op_num_threads = THREADS
            options.inter_op_num_threads = 1
            session = onnxruntime.InferenceSession(
                str(self.model_path), sess_options=options, providers=["CPUExecutionProvider"]
            )
            return kokoro_class.from_session(session, str(self.voices_path))
        except (ImportError, AttributeError, TypeError):
            return kokoro_class(str(self.model_path), str(self.voices_path))  # An older kokoro-onnx: its own defaults.

    def _blend(self, kokoro):
        weights = PRESETS.get(self._voice) or {self._voice: 1.0}
        total = sum(weights.values()) or 1.0
        style = None
        for name, weight in weights.items():
            part = kokoro.get_voice_style(name) * (weight / total)
            style = part if style is None else style + part
        return style.astype("float32")
