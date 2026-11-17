"""The interface every text-to-speech engine implements, and the audio it returns."""

from __future__ import annotations

import array
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import ClassVar


class SynthesisError(Exception):
    """Speech could not be produced. The message is shown to the user, so write it for a human."""


@dataclass
class Speech:
    """A spoken clip: mono float samples (-1..1) at `sample_rate` Hz.

    Like speech/audio.py's AudioClip, but at the engine's own rate: speech
    models produce 22-24 kHz audio, and downsampling it to 16 kHz for no
    reason would make Alter Ego sound dull.
    """

    samples: array.array  # typecode "f"
    sample_rate: int

    @classmethod
    def empty(cls, sample_rate: int = 24000) -> Speech:
        return cls(array.array("f"), sample_rate)

    @classmethod
    def silence(cls, seconds: float, sample_rate: int = 24000) -> Speech:
        return cls(array.array("f", bytes(4 * int(seconds * sample_rate))), sample_rate)

    @property
    def duration(self) -> float:
        return len(self.samples) / self.sample_rate if self.sample_rate else 0.0


class Synthesizer(ABC):
    # Short id stored in the config file, and the label shown in menus.
    id: ClassVar[str] = ""
    label: ClassVar[str] = ""
    # Whether the pitch lift and the CRT tone apply. They exist to make a generic voice sound
    # younger and computer-like; an engine that already produces the character's own voice
    # is played exactly as it comes out.
    shape_voice: ClassVar[bool] = True

    @abstractmethod
    def describe(self) -> str:
        """One line saying what does the talking, e.g. "local Kokoro voice 'alter_ego'"."""

    @abstractmethod
    def synthesize(self, text: str, speed: float = 1.0) -> Speech:
        """Turn text into speech. Runs on a worker thread, may take seconds. Raises SynthesisError.

        `speed` is a tempo factor: 1.0 normal, below slower, above faster.
        """

    @property
    def ready(self) -> bool:
        """False while something slow (a model download or load) still has to happen first."""
        return True

    @property
    def needs_download(self) -> bool:
        """True when prepare() would fetch something large from the internet. Asked before the first use."""
        return False

    def prepare(self) -> str:
        """Do the slow part now (download/load a model, check a server). Returns a human-readable summary."""
        return f"{self.describe()} is ready."
