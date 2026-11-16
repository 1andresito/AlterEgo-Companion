"""Microphone capture with Qt Multimedia (bundled with PySide6, no extra install).

Two ways to use it:

- start() then stop(): everything in between is buffered and stop() returns
  it as one AudioClip. Push to talk works like this.
- start(stream=True): audio is handed out as it arrives through the `chunk`
  signal and nothing is kept. Hands-free mode works like this.

Nothing is captured outside start()/stop(), and nothing is written to disk.
"""

from __future__ import annotations

from PySide6.QtCore import QIODevice, QObject, Signal
from PySide6.QtMultimedia import QAudioDevice, QAudioFormat, QAudioSource, QMediaDevices

try:  # Qt 6.7 renamed the QAudio namespace to QtAudio; the error enum lives there.
    from PySide6.QtMultimedia import QtAudio as _QtAudio
except ImportError:  # pragma: no cover - older PySide6
    from PySide6.QtMultimedia import QAudio as _QtAudio

from .audio import SAMPLE_RATE, AudioClip, clip_from_pcm

NO_ERROR = _QtAudio.Error.NoError

DEFAULT_DEVICE = ""  # Config value meaning "the system default microphone".

_FORMAT_NAMES = {
    QAudioFormat.SampleFormat.UInt8: "uint8",
    QAudioFormat.SampleFormat.Int16: "int16",
    QAudioFormat.SampleFormat.Int32: "int32",
    QAudioFormat.SampleFormat.Float: "float",
}


class MicrophoneError(Exception):
    """The microphone could not be used. Shown to the user, so written for a human."""


class MicrophoneRecorder(QObject):
    chunk = Signal(object)  # AudioClip: a piece of audio, only in streaming mode

    def __init__(self, device_name: str = DEFAULT_DEVICE, parent: QObject | None = None):
        super().__init__(parent)
        self._device_name = device_name
        self._source: QAudioSource | None = None
        self._io: QIODevice | None = None
        self._format: QAudioFormat | None = None
        self._buffer = bytearray()
        self._stream = False
        self._pending = b""  # Streaming: bytes of an incomplete frame, waiting for the rest

    @staticmethod
    def available_devices() -> list[str]:
        return [device.description() for device in QMediaDevices.audioInputs()]

    def set_device(self, device_name: str) -> None:
        self._device_name = device_name

    @property
    def recording(self) -> bool:
        return self._source is not None

    def start(self, stream: bool = False) -> None:
        if self.recording:
            return
        self._stream = stream
        self._pending = b""
        device = self._pick_device()
        audio_format = QAudioFormat()
        audio_format.setSampleRate(SAMPLE_RATE)
        audio_format.setChannelCount(1)
        audio_format.setSampleFormat(QAudioFormat.SampleFormat.Int16)
        if not device.isFormatSupported(audio_format):
            audio_format = device.preferredFormat()  # Converted to 16 kHz mono in stop().

        source = QAudioSource(device, audio_format, self)
        io = source.start()
        if io is None or source.error() != NO_ERROR:
            source.deleteLater()
            raise MicrophoneError(
                f"I couldn't open the microphone '{device.description()}'. "
                "Is another program using it, or is microphone access switched off in Windows settings?"
            )
        self._buffer = bytearray()
        self._source, self._io, self._format = source, io, audio_format
        io.readyRead.connect(self._drain)

    def stop(self) -> AudioClip:
        source, io, audio_format = self._source, self._io, self._format
        if source is None or io is None or audio_format is None:
            return AudioClip.empty()
        self._drain()
        io.readyRead.disconnect(self._drain)
        source.stop()
        source.deleteLater()
        self._source = self._io = self._format = None

        if self._stream:
            self._buffer = bytearray()
            return AudioClip.empty()
        clip = self._convert(bytes(self._buffer), audio_format)
        self._buffer = bytearray()
        return clip

    def _drain(self) -> None:
        if self._io is None or self._format is None:
            return
        data = self._io.readAll().data()
        if not self._stream:
            self._buffer += data
            return
        data = self._pending + data
        frame_size = max(1, self._format.bytesPerFrame())
        usable = len(data) - len(data) % frame_size
        self._pending = data[usable:]
        if usable:
            self.chunk.emit(self._convert(data[:usable], self._format))

    @staticmethod
    def _convert(data: bytes, audio_format: QAudioFormat) -> AudioClip:
        sample_format = _FORMAT_NAMES.get(audio_format.sampleFormat(), "int16")
        return clip_from_pcm(data, audio_format.sampleRate(), audio_format.channelCount(), sample_format)

    def _pick_device(self) -> QAudioDevice:
        if self._device_name:
            for device in QMediaDevices.audioInputs():
                if device.description() == self._device_name:
                    return device
            print(f"Warning: microphone '{self._device_name}' not found, using the default one.")
        device = QMediaDevices.defaultAudioInput()
        if device.isNull():
            raise MicrophoneError("I can't find a microphone. Plug one in, or check the Windows sound settings.")
        return device
