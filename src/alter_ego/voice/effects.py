"""Shaping the voice: a pitch lift for a younger sound, and a hint of "speaking from inside a monitor".

Everything here works on a Speech clip and returns a new one. The processing
uses NumPy when it is installed (it comes with every speech package); without
it the clip is returned unchanged, so the app never depends on it.

Pitch: the engines have no pitch control, so the clip is produced a little
slower and then played back a little faster. Raising a voice by `semitones`
means a factor of 2 ** (semitones / 12) in both. The result keeps the original
tempo and sounds higher, with slightly raised resonances, which is exactly
what makes a voice sound younger.
"""

from __future__ import annotations

import array
import math

from .synthesizer import Speech

# Settings bounds, so a typo in the settings file cannot produce a chipmunk.
MIN_SEMITONES = -6.0
MAX_SEMITONES = 8.0
MIN_SPEED = 0.6
MAX_SPEED = 1.6


def pitch_factor(semitones: float) -> float:
    semitones = max(MIN_SEMITONES, min(MAX_SEMITONES, float(semitones)))
    return 2.0 ** (semitones / 12.0)


def clamp_speed(speed: float) -> float:
    try:
        return max(MIN_SPEED, min(MAX_SPEED, float(speed)))
    except (TypeError, ValueError):
        return 1.0


def _numpy():
    try:
        import numpy as np
    except ImportError:
        return None
    return np


def resample(speech: Speech, factor: float) -> Speech:
    """Play the clip `factor` times faster (pitch and tempo both rise), keeping the sample rate."""
    if factor == 1.0 or len(speech.samples) < 2:
        return speech
    np = _numpy()
    if np is None:
        return speech
    samples = np.frombuffer(speech.samples.tobytes(), dtype=np.float32)
    positions = np.arange(0, len(samples) - 1, factor)
    out = np.interp(positions, np.arange(len(samples)), samples).astype(np.float32)
    return Speech(array.array("f", out.tobytes()), speech.sample_rate)


def crt_voice(speech: Speech, amount: float = 1.0) -> Speech:
    """A light "small speaker inside a monitor" tone.

    Band-limits the voice (no deep lows, softened highs), adds a faint short
    echo that gives the metallic ring of a tiny speaker, and a touch of
    saturation. Mixed with the dry voice by `amount` (0 = off, 1 = full
    effect), and kept subtle so the words stay clear.
    """
    np = _numpy()
    if np is None or amount <= 0 or len(speech.samples) < 16:
        return speech
    amount = min(1.0, amount)
    rate = speech.sample_rate
    dry = np.frombuffer(speech.samples.tobytes(), dtype=np.float32).astype(np.float64)

    # Zero-phase band-pass in the frequency domain (no filter state, no loops).
    spectrum = np.fft.rfft(dry)
    freqs = np.fft.rfftfreq(len(dry), 1.0 / rate)
    with np.errstate(divide="ignore"):
        high_pass = 1.0 / np.sqrt(1.0 + (160.0 / np.maximum(freqs, 1e-6)) ** 4)
        low_pass = 1.0 / np.sqrt(1.0 + (freqs / 6500.0) ** 4)
    wet = np.fft.irfft(spectrum * high_pass * low_pass, n=len(dry))

    # A very short delayed copy: the resonance of a small enclosure.
    delay = max(1, int(rate * 0.0011))
    wet[delay:] += 0.18 * wet[:-delay]

    # Gentle saturation for a slightly electronic edge.
    wet = np.tanh(1.6 * wet) / math.tanh(1.6)

    mixed = (1.0 - 0.85 * amount) * dry + 0.85 * amount * wet
    peak = float(np.max(np.abs(mixed))) if len(mixed) else 0.0
    if peak > 0.95:
        mixed *= 0.95 / peak
    return Speech(array.array("f", mixed.astype(np.float32).tobytes()), rate)


def to_pcm16(speech: Speech) -> bytes:
    """The clip as little-endian 16-bit PCM, for the sound card."""
    np = _numpy()
    if np is not None:
        samples = np.frombuffer(speech.samples.tobytes(), dtype=np.float32)
        return (np.clip(samples, -1.0, 1.0) * 32767).astype("<i2").tobytes()
    pcm = array.array("h", (int(max(-1.0, min(1.0, value)) * 32767) for value in speech.samples))
    return pcm.tobytes()


def from_pcm16(data: bytes, sample_rate: int, channels: int = 1) -> Speech:
    """The reverse of to_pcm16, averaging extra channels into one."""
    channels = max(1, channels)
    usable = len(data) - len(data) % (2 * channels)
    raw = array.array("h")
    raw.frombytes(data[:usable])
    np = _numpy()
    if np is not None:
        samples = np.frombuffer(raw.tobytes(), dtype="<i2").astype(np.float32) / 32768.0
        if channels > 1:
            samples = samples.reshape(-1, channels).mean(axis=1).astype(np.float32)
        return Speech(array.array("f", samples.tobytes()), sample_rate)
    scaled = array.array("f", (value / 32768.0 for value in raw))
    if channels > 1:
        scaled = array.array("f", (sum(scaled[i:i + channels]) / channels for i in range(0, len(scaled), channels)))
    return Speech(scaled, sample_rate)


def with_tail(speech: Speech, seconds: float = 0.08) -> Speech:
    """A short silence after the clip, so the sound card never cuts the last syllable."""
    if seconds <= 0:
        return speech
    tail = array.array("f", bytes(4 * int(seconds * speech.sample_rate)))
    return Speech(speech.samples + tail, speech.sample_rate)
