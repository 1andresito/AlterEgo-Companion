"""Plays speech clips through the speakers with Qt Multimedia (bundled with PySide6).

One clip at a time, in "pull" mode: the sink reads from an in-memory buffer
and reports when it has run dry, which is how we know the clip has ended.
"""

from __future__ import annotations

from PySide6.QtCore import QBuffer, QByteArray, QObject, Signal, Slot
from PySide6.QtMultimedia import QAudioDevice, QAudioFormat, QAudioSink, QMediaDevices

try:  # Qt 6.7 renamed the QAudio namespace to QtAudio; the state enum lives there.
    from PySide6.QtMultimedia import QtAudio as _QtAudio
except ImportError:  # pragma: no cover - older PySide6
    from PySide6.QtMultimedia import QAudio as _QtAudio

from ..speech.audio import _resample
from .effects import to_pcm16, with_tail
from .synthesizer import Speech

DEFAULT_DEVICE = ""  # Config value meaning "the system default speakers".


class PlaybackError(Exception):
    """The speakers could not be used. Shown to the user, so written for a human."""


class SpeechPlayer(QObject):
    finished = Signal()  # The clip ended, or stop() was called while one was playing.

    def __init__(self, device_name: str = DEFAULT_DEVICE, volume: float = 1.0, parent: QObject | None = None):
        super().__init__(parent)
        self._device_name = device_name
        self._volume = max(0.0, min(1.0, volume))
        self._sink: QAudioSink | None = None
        self._buffer: QBuffer | None = None

    @staticmethod
    def available_devices() -> list[str]:
        return [device.description() for device in QMediaDevices.audioOutputs()]

    def set_device(self, device_name: str) -> None:
        self._device_name = device_name

    def set_volume(self, volume: float) -> None:
        self._volume = max(0.0, min(1.0, volume))
        if self._sink is not None:
            self._sink.setVolume(self._volume)

    @property
    def playing(self) -> bool:
        return self._sink is not None

    def play(self, speech: Speech) -> None:
        """Start playing a clip. A clip already playing is stopped first. Raises PlaybackError."""
        self.stop()
        if not len(speech.samples):
            return
        device = self._pick_device()
        audio_format = QAudioFormat()
        audio_format.setSampleRate(speech.sample_rate)
        audio_format.setChannelCount(1)
        audio_format.setSampleFormat(QAudioFormat.SampleFormat.Int16)
        if not device.isFormatSupported(audio_format):
            # Rare: the device insists on its own rate. Convert the clip to it.
            rate = device.preferredFormat().sampleRate() or 48000
            speech = Speech(_resample(speech.samples, speech.sample_rate, rate), rate)
            audio_format.setSampleRate(rate)
            if not device.isFormatSupported(audio_format):
                raise PlaybackError(f"The speakers '{device.description()}' don't accept 16-bit mono audio, so I can't talk.")

        buffer = QBuffer(self)
        buffer.setData(QByteArray(to_pcm16(with_tail(speech))))
        buffer.open(QBuffer.OpenModeFlag.ReadOnly)
        sink = QAudioSink(device, audio_format, self)
        sink.setVolume(self._volume)
        sink.stateChanged.connect(self._on_state)
        self._sink, self._buffer = sink, buffer
        sink.start(buffer)
        if sink.error() != _QtAudio.Error.NoError:
            self._teardown()
            raise PlaybackError(f"I couldn't open the speakers '{device.description()}'. Is another program using them?")

    def stop(self) -> None:
        if self._sink is None:
            return
        self._teardown()
        self.finished.emit()

    @Slot(_QtAudio.State)
    def _on_state(self, state) -> None:
        # Idle = the buffer ran dry = the clip has been played to the end.
        if state in (_QtAudio.State.IdleState, _QtAudio.State.StoppedState) and self._sink is not None:
            self._teardown()
            self.finished.emit()

    def _teardown(self) -> None:
        sink, buffer = self._sink, self._buffer
        self._sink = self._buffer = None
        if sink is not None:
            sink.stateChanged.disconnect(self._on_state)
            sink.stop()
            sink.deleteLater()
        if buffer is not None:
            buffer.close()
            buffer.deleteLater()

    def _pick_device(self) -> QAudioDevice:
        if self._device_name:
            for device in QMediaDevices.audioOutputs():
                if device.description() == self._device_name:
                    return device
            print(f"Warning: speakers '{self._device_name}' not found, using the default ones.")
        device = QMediaDevices.defaultAudioOutput()
        if device.isNull():
            raise PlaybackError("I can't find any speakers or headphones to talk through.")
        return device
