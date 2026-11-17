"""Alter Ego with a character's own voice: Kokoro speech converted with RVC, all on this computer.

Kokoro (kokoro_local.py) says the words; RVC (Retrieval-based Voice Conversion)
then changes the timbre to that of a trained voice model, so the delivery is
Kokoro's but the voice is the character's. Conversion runs through the
optional `infer-rvc-python` package (PyTorch, no fairseq), on an NVIDIA GPU
when PyTorch has CUDA and sees one, else on the CPU (device.py decides per
machine). On a desktop CPU a sentence converts in about 0.6 times its own
length; the sentence-by-sentence pipeline in speaker.py absorbs that.

What is needed, and where it comes from:

- The voice model: `alter_ego.pth` and its `alter_ego.index`, trained by
  the project's owner and shipped with the project in assets/voice/ (stored
  with Git LFS). Alter Ego has exactly one voice: there is no menu, setting
  or folder to supply another model, pitch or quality; the tuning below is
  part of the code.
- Two base models shared by every RVC voice, downloaded once on request
  into the data folder (about 535 MB): the RMVPE pitch tracker and the
  HuBERT speech encoder.
- Python 3.10 to 3.13 for the `infer-rvc-python` package. Without it the
  engine explains what to install; the rest of Alter Ego runs as usual.
"""

from __future__ import annotations

import array
import os
import threading
import urllib.error
import urllib.request
import warnings
from pathlib import Path
from typing import Callable

from ..providers.https import urlopen
from .device import CUDA, compute_device, cpu_threads, describe_device, use_cpu
from .kokoro_local import KokoroSynthesizer
from .synthesizer import Speech, Synthesizer, SynthesisError

INSTALL_HINT = (
    "Install it with the two lines at the top of requirements-character-voice.txt "
    "(it needs Python 3.10 to 3.13; make the virtual environment with one of those)"
)
CHARACTER_DIR = "voice"  # Folder inside assets/ that holds the one voice model, shipped with the project.
CHARACTER_MODEL = "alter_ego.pth"
MODEL_HINT = (
    "My voice file (assets/voice/alter_ego.pth) is missing. It comes with the project through Git LFS: "
    "install Git LFS, run  git lfs pull  in the project folder, then restart me."
)
# A file Git LFS has not downloaded yet is a short text pointer that starts with this line.
LFS_POINTER_PREFIX = b"version https://git-lfs"
LFS_POINTER_MAX_BYTES = 1024

RMVPE_URL = "https://huggingface.co/r3gm/sonitranslate_voice_models/resolve/main/rmvpe.pt"
HUBERT_URL = "https://huggingface.co/r3gm/hubert_base/resolve/main/"
RMVPE_FILE = "rmvpe.pt"
HUBERT_DIR = "hubert_base"
HUBERT_FILES = ("config.json", "model.safetensors")
BASE_DOWNLOAD_MB = 535

F0_METHODS = ["rmvpe+", "rmvpe", "pm"]  # pitch trackers: best first, "pm" is fastest and roughest
# The fixed tuning of Alter Ego's voice. RVC keeps the pitch it is given and changes only the
# timbre, so the Kokoro blend (median about 193 Hz) is raised to the character's own speaking
# pitch: +7 semitones gave a median of 283-287 Hz against 283 Hz in the training clip (measured
# 2026-11-16). The index pulls the timbre toward the training voice, strongly enough to sound
# like the character without its recording artefacts.
DEFAULT_F0_METHOD = "rmvpe+"
DEFAULT_INDEX_RATE = 0.75
DEFAULT_PITCH = 7
TAG = "alter_ego"  # The converter's name for the one configured voice.


def find_index(model_path: Path) -> Path | None:
    """The .index file that belongs to a model: same name, else the only .index in the folder."""
    same_name = model_path.with_suffix(".index")
    if same_name.is_file():
        return same_name
    candidates = sorted(model_path.parent.glob("*.index"))
    return candidates[0] if len(candidates) == 1 else None


def is_lfs_pointer(path: Path) -> bool:
    """True when the file is Git LFS's placeholder, i.e. the real model was never downloaded."""
    try:
        if path.stat().st_size > LFS_POINTER_MAX_BYTES:
            return False
        with open(path, "rb") as handle:
            return handle.read(len(LFS_POINTER_PREFIX)) == LFS_POINTER_PREFIX
    except OSError:
        return False


def find_character_model(folder: Path) -> Path | None:
    """Alter Ego's one voice model in the given folder, or None if it is missing or only an LFS pointer."""
    model = folder / CHARACTER_MODEL
    if not model.is_file():
        return None
    if is_lfs_pointer(model):
        print(f"Warning: {model} is a Git LFS pointer, not the voice model. Run 'git lfs pull'. Using the stand-in voice.")
        return None
    return model


class CharacterVoiceSynthesizer(Synthesizer):
    id = "kokoro_rvc"
    label = "Alter Ego's character voice (Kokoro + RVC)"
    shape_voice = False  # The converted voice is the character's; the pitch lift and CRT tone would spoil it.

    def __init__(
        self,
        kokoro: KokoroSynthesizer,
        model_path: str | Path = "",
        index_path: str | Path = "",
        pitch_semitones: float = DEFAULT_PITCH,
        index_rate: float = DEFAULT_INDEX_RATE,
        f0_method: str = DEFAULT_F0_METHOD,
        models_dir: str | Path = ".",
        threads: int = 0,
        converter_factory: Callable[[Path, Path], object] | None = None,
    ):
        self.kokoro = kokoro
        self._model_path = Path(model_path) if str(model_path) else None
        self._index_path = Path(index_path) if str(index_path) else None
        self._pitch = int(round(max(-24.0, min(24.0, float(pitch_semitones)))))
        self._index_rate = max(0.0, min(1.0, float(index_rate)))
        self._f0_method = f0_method if f0_method in F0_METHODS else DEFAULT_F0_METHOD
        self._dir = Path(models_dir)
        self._threads = max(0, int(threads))
        self._converter_factory = converter_factory  # Tests inject a fake converter here.
        self._converter = None
        self._lock = threading.Lock()

    # ----- Paths -----

    @property
    def model_path(self) -> Path | None:
        return self._model_path

    @property
    def index_path(self) -> Path | None:
        if self._index_path is not None:
            return self._index_path
        return find_index(self._model_path) if self._model_path is not None else None

    @property
    def rmvpe_path(self) -> Path:
        return self._dir / RMVPE_FILE

    @property
    def hubert_dir(self) -> Path:
        return self._dir / HUBERT_DIR

    @property
    def pitch_semitones(self) -> int:
        return self._pitch

    # ----- Synthesizer interface -----

    def describe(self) -> str:
        voice = self._model_path.stem if self._model_path is not None else "no voice model chosen"
        return f"local Kokoro converted to the voice '{voice}' (RVC, {self._f0_method})"

    @property
    def ready(self) -> bool:
        return self.kokoro.ready and self._converter is not None

    @property
    def needs_download(self) -> bool:
        return self.kokoro.needs_download or not self._base_models_present()

    @property
    def download_size_mb(self) -> int:
        size = self.kokoro.download_size_mb if self.kokoro.needs_download else 0
        if not self._base_models_present():
            size += BASE_DOWNLOAD_MB
        return size

    def prepare(self) -> str:
        self.kokoro.prepare()
        downloaded = not self._base_models_present()
        self._download()
        self._load()
        name = self._model_path.stem if self._model_path is not None else "?"
        if downloaded:
            return f"My voice is downloaded and ready. I'll speak as '{name}' from now on."
        return f"My voice is loaded and ready: Kokoro, converted to '{name}'."

    def synthesize(self, text: str, speed: float = 1.0) -> Speech:
        speech = self.kokoro.synthesize(text, speed)
        if not len(speech.samples):
            return speech
        return self._convert(speech)

    # ----- Files and models -----

    def _base_models_present(self) -> bool:
        return self.rmvpe_path.is_file() and all((self.hubert_dir / name).is_file() for name in HUBERT_FILES)

    def _download(self) -> None:
        wanted = [(RMVPE_URL, self.rmvpe_path)] + [(HUBERT_URL + name, self.hubert_dir / name) for name in HUBERT_FILES]
        for url, target in wanted:
            if target.is_file():
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            partial = target.with_suffix(target.suffix + ".part")
            try:
                request = urllib.request.Request(url, headers={"User-Agent": "AlterEgo-Companion"})
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
                    f"I couldn't download part of my voice ({target.name}): {getattr(error, 'reason', error)}. "
                    "Check the internet connection and try again from the Spoken replies menu."
                ) from None

    def _load(self):
        with self._lock:
            if self._converter is not None:
                return self._converter
            if self._model_path is None:
                raise SynthesisError(f"I don't have a character voice to use yet. {MODEL_HINT}")
            if not self._model_path.is_file():
                raise SynthesisError(f"I can't find the character voice model '{self._model_path}'. {MODEL_HINT}")
            if not self._base_models_present():
                raise SynthesisError(
                    f"I can't use the character voice yet: its base models aren't downloaded. "
                    f"Choose Spoken replies -> Download my voice (about {BASE_DOWNLOAD_MB} MB, once)."
                )
            if self._converter_factory is not None:
                converter = self._converter_factory(self.rmvpe_path, self.hubert_dir)
            else:
                converter = self._make_converter()
            try:
                self._configure(converter)
            except Exception as error:  # noqa: BLE001 - whatever the package raises, the app must survive
                if self._converter_factory is None and compute_device() == CUDA:
                    # A GPU that cannot hold the models (too little memory, driver trouble): use the CPU.
                    print(f"Warning: the voice could not load on the GPU ({type(error).__name__}: {error}); using the CPU.")
                    use_cpu()
                    converter = self._make_converter()
                    try:
                        self._configure(converter)
                    except Exception as cpu_error:  # noqa: BLE001
                        raise self._setup_error(cpu_error) from None
                else:
                    raise self._setup_error(error) from None
            self._converter = converter
            return converter

    def _setup_error(self, error: Exception) -> SynthesisError:
        name = self._model_path.name if self._model_path is not None else "?"
        return SynthesisError(f"I couldn't set up the character voice '{name}': {type(error).__name__}: {error}")

    def _configure(self, converter) -> None:
        converter.apply_conf(
            tag=TAG,
            file_model=str(self._model_path),
            pitch_algo=self._f0_method,
            pitch_lvl=self._pitch,
            file_index=str(self.index_path) if self.index_path is not None else "",
            index_influence=self._index_rate,
            respiration_median_filtering=3,
            envelope_ratio=0.25,
            consonant_breath_protection=0.33,
        )

    def _make_converter(self):
        try:
            with warnings.catch_warnings():
                warnings.simplefilter("ignore")  # Its dependencies still import deprecated setuptools bits.
                import torch
                from infer_rvc_python import BaseLoader
        except ImportError:
            raise SynthesisError(f"I can't use a character voice yet: the voice-conversion package is missing. {INSTALL_HINT}") from None
        on_gpu = compute_device() == CUDA
        if not on_gpu:
            torch.set_num_threads(self._threads or cpu_threads())
        print(f"Alter Ego: character voice on the {describe_device()}")
        try:
            return BaseLoader(only_cpu=not on_gpu, hubert_path=str(self.hubert_dir), rmvpe_path=str(self.rmvpe_path))
        except Exception as error:  # noqa: BLE001
            raise SynthesisError(f"I couldn't start the voice converter: {type(error).__name__}: {error}") from None

    def _convert(self, speech: Speech) -> Speech:
        converter = self._load()
        import numpy as np  # A dependency of the converter, so present once _load() succeeded.

        samples = np.frombuffer(speech.samples.tobytes(), dtype=np.float32)
        try:
            result, rate = converter.generate_from_cache(audio_data=(samples, speech.sample_rate), tag=TAG)
        except Exception as error:  # noqa: BLE001
            raise SynthesisError(f"The character voice failed: {type(error).__name__}: {error}") from None
        out = np.asarray(result)
        if out.dtype.kind in "iu":
            out = out.astype(np.float32) / 32768.0  # The converter returns 16-bit samples.
        else:
            out = out.astype(np.float32)
            if len(out) and float(np.abs(out).max()) > 1.5:
                out = out / 32768.0
        if out.ndim > 1:
            out = out.mean(axis=1).astype(np.float32)
        return Speech(array.array("f", out.tobytes()), int(rate))
