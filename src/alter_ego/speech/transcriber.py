"""The interface every speech-recognition engine implements."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import ClassVar

from .audio import AudioClip


class TranscriptionError(Exception):
    """Speech could not be recognised. The message is shown to the user, so write it for a human."""


class Transcriber(ABC):
    # Short id stored in the config file, and the label shown in menus.
    id: ClassVar[str] = ""
    label: ClassVar[str] = ""

    @abstractmethod
    def describe(self) -> str:
        """One line saying what does the recognising, e.g. "local Whisper 'base'"."""

    @abstractmethod
    def transcribe(self, clip: AudioClip) -> str:
        """Turn speech into text. Runs on a worker thread, may take seconds. Raises TranscriptionError.

        Returns "" when no words were recognised.
        """

    @property
    def ready(self) -> bool:
        """False while something slow (a model download or load) still has to happen first."""
        return True

    def prepare(self) -> str:
        """Do the slow part now (download/load a model, check a server). Returns a human-readable summary."""
        return f"{self.describe()} is ready."
