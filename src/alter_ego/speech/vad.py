"""Cuts a continuous microphone stream into utterances, using loudness only.

Hands-free mode keeps the microphone open. Running Whisper on everything
would waste CPU, so this detector watches the energy of 20 ms frames: an
utterance starts when a few frames in a row are clearly louder than the
background noise and ends after a short silence. Only those utterances are
passed on for recognition; the rest of the audio is dropped at once.

No external dependencies, and nothing here knows about Qt or threads: feed()
takes samples and returns finished utterances.
"""

from __future__ import annotations

import array
import math

from .audio import SAMPLE_RATE, AudioClip

FRAME_MS = 20
FRAME_SAMPLES = SAMPLE_RATE * FRAME_MS // 1000     # 320
PRE_ROLL_FRAMES = 15        # 300 ms kept from before the speech started, so first syllables are not cut
START_FRAMES = 3            # this many loud frames in a row start an utterance
END_SILENCE_FRAMES = 35     # 700 ms of quiet ends it
MIN_SPEECH_FRAMES = 12      # utterances with less speech than this (240 ms) are clicks and coughs
MAX_UTTERANCE_FRAMES = 600  # 12 s: cut and hand over, the speaker is not pausing
MIN_SPEECH_RMS = 0.012      # never treat anything quieter than this as speech (the "normal" sensitivity)
# Voice -> Wake sensitivity: how loud a sound must be to count as speech at all.
SENSITIVITY_LEVELS: dict[str, float] = {"low": 0.025, "normal": MIN_SPEECH_RMS, "high": 0.005}
DEFAULT_SENSITIVITY = "normal"
NOISE_FACTOR = 3.5          # speech must be this many times louder than the background
# The background level is a rising minimum: it drops at once to any quieter frame and creeps
# up by this factor per frame otherwise (doubling in about 1.4 s). Gaps between words keep it
# low during speech; a fan or hum that never stops is absorbed within a few seconds.
NOISE_RISE = 1.01
MIN_NOISE_RMS = 0.001
INITIAL_NOISE_RMS = 0.004


def frame_rms(samples: array.array, start: int, end: int) -> float:
    count = end - start
    if count <= 0:
        return 0.0
    return math.sqrt(sum(value * value for value in samples[start:end]) / count)


class UtteranceDetector:
    def __init__(self, min_speech_rms: float = MIN_SPEECH_RMS) -> None:
        self.min_speech_rms = min_speech_rms
        self._carry = array.array("f")             # samples not yet forming a whole frame
        self._pre_roll: list[array.array] = []     # the last few frames before speech started
        self._utterance: array.array | None = None
        self._loud_run = 0
        self._quiet_run = 0
        self._speech_frames = 0
        self._frames_in_utterance = 0
        self.noise_rms = INITIAL_NOISE_RMS

    @property
    def speaking(self) -> bool:
        return self._utterance is not None

    def reset(self) -> None:
        self.__init__(self.min_speech_rms)

    def feed(self, samples: array.array) -> list[AudioClip]:
        """Add samples (16 kHz mono floats); returns the utterances that finished during this call."""
        finished: list[AudioClip] = []
        data = self._carry + samples if self._carry else samples
        whole = len(data) - len(data) % FRAME_SAMPLES
        self._carry = data[whole:]
        for start in range(0, whole, FRAME_SAMPLES):
            frame = data[start:start + FRAME_SAMPLES]
            clip = self._feed_frame(frame)
            if clip is not None:
                finished.append(clip)
        return finished

    def _feed_frame(self, frame: array.array) -> AudioClip | None:
        rms = frame_rms(frame, 0, len(frame))
        threshold = max(self.min_speech_rms, self.noise_rms * NOISE_FACTOR)
        loud = rms > threshold
        self.noise_rms = max(MIN_NOISE_RMS, min(rms, self.noise_rms * NOISE_RISE))

        if self._utterance is None:
            self._pre_roll.append(frame)
            if len(self._pre_roll) > PRE_ROLL_FRAMES:
                self._pre_roll.pop(0)
            self._loud_run = self._loud_run + 1 if loud else 0
            if self._loud_run >= START_FRAMES:
                self._utterance = array.array("f")
                for earlier in self._pre_roll:
                    self._utterance.extend(earlier)
                self._frames_in_utterance = len(self._pre_roll)
                self._pre_roll = []
                self._speech_frames = self._loud_run
                self._quiet_run = 0
                self._loud_run = 0
            return None

        self._utterance.extend(frame)
        self._frames_in_utterance += 1
        if loud:
            self._speech_frames += 1
            self._quiet_run = 0
        else:
            self._quiet_run += 1

        if self._quiet_run >= END_SILENCE_FRAMES or self._frames_in_utterance >= MAX_UTTERANCE_FRAMES:
            return self._finish()
        return None

    def _finish(self) -> AudioClip | None:
        utterance = self._utterance
        speech_frames = self._speech_frames
        self._utterance = None
        self._speech_frames = 0
        self._frames_in_utterance = 0
        self._quiet_run = 0
        if utterance is None or speech_frames < MIN_SPEECH_FRAMES:
            return None
        return AudioClip(utterance)
