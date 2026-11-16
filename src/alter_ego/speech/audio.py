"""Audio clips: whatever the microphone delivers becomes 16 kHz mono float samples.

Speech models want exactly that format, so the conversion happens once, here,
and every transcriber can rely on it. Pure standard library (array + wave):
clips are a few seconds long, so plain Python loops are fast enough.
"""

from __future__ import annotations

import array
import io
import wave
from dataclasses import dataclass

SAMPLE_RATE = 16000

# Name -> (array typecode, bytes per sample, divisor to reach -1..1, offset).
_PCM_FORMATS: dict[str, tuple[str, int, float, float]] = {
    "uint8": ("B", 1, 128.0, 128.0),
    "int16": ("h", 2, 32768.0, 0.0),
    "int32": ("i", 4, 2147483648.0, 0.0),
    "float": ("f", 4, 1.0, 0.0),
}


@dataclass
class AudioClip:
    samples: array.array  # typecode "f", mono, SAMPLE_RATE, values in -1..1

    @classmethod
    def empty(cls) -> AudioClip:
        return cls(array.array("f"))

    @property
    def duration(self) -> float:
        """Length in seconds."""
        return len(self.samples) / SAMPLE_RATE

    def peak(self) -> float:
        """Loudest sample, 0..1. Near zero means silence (or a muted microphone)."""
        return max((abs(value) for value in self.samples), default=0.0)

    def to_wav_bytes(self) -> bytes:
        """The clip as a 16-bit WAV file, for APIs that take an upload."""
        pcm = array.array("h", (int(max(-1.0, min(1.0, value)) * 32767) for value in self.samples))
        buffer = io.BytesIO()
        with wave.open(buffer, "wb") as wav:
            wav.setnchannels(1)
            wav.setsampwidth(2)
            wav.setframerate(SAMPLE_RATE)
            wav.writeframes(pcm.tobytes())
        return buffer.getvalue()


def clip_from_pcm(data: bytes, sample_rate: int, channels: int, sample_format: str) -> AudioClip:
    """Convert raw interleaved PCM (as a sound card delivers it) into an AudioClip.

    `sample_format` is one of "uint8", "int16", "int32", "float". Extra channels
    are averaged into one, and the rate is changed to SAMPLE_RATE with linear
    interpolation, which is plenty for speech.
    """
    if sample_format not in _PCM_FORMATS:
        raise ValueError(f"unsupported sample format: {sample_format}")
    typecode, width, divisor, offset = _PCM_FORMATS[sample_format]
    channels = max(1, channels)
    frame_size = width * channels
    usable = len(data) - len(data) % frame_size
    raw = array.array(typecode)
    raw.frombytes(data[:usable])

    if sample_format == "float":
        scaled = array.array("f", raw)
    else:
        scaled = array.array("f", ((value - offset) / divisor for value in raw))

    if channels > 1:
        per_channel = [scaled[c::channels] for c in range(channels)]
        mono = array.array("f", (sum(frame) / channels for frame in zip(*per_channel)))
    else:
        mono = scaled

    return AudioClip(_resample(mono, sample_rate, SAMPLE_RATE))


def _resample(samples: array.array, source_rate: int, target_rate: int) -> array.array:
    if source_rate == target_rate or len(samples) < 2:
        return samples
    ratio = source_rate / target_rate
    count = int(len(samples) / ratio)
    out = array.array("f", bytes(4 * count))
    last = len(samples) - 1
    for i in range(count):
        position = i * ratio
        j = int(position)
        fraction = position - j
        a = samples[j]
        b = samples[j + 1] if j < last else a
        out[i] = a + (b - a) * fraction
    return out
