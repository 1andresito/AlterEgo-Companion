"""Hands-free mode: say "Hey Alter Ego", then say what you want.

    OFF --start()--> WAITING --(wake phrase heard)--> AWAKE --(utterance)--> TRANSCRIBING --> WAITING
                        ^                                |  (nothing said in time)             |
                        +--------------------------------+-------------------------------------+

    While the reply to a hands-free request is spoken, with "interrupt by talking" on:
    WAITING (watching) --(the user starts to speak)--> interrupted, AWAKE: what they say is the new request

While WAITING the microphone stays open and the UtteranceDetector cuts the
stream into utterances; each one is transcribed with the small, fast wake
model and compared with the wake phrase. A command said in the same breath
("Hey Alter Ego, what time is it") is used at once; otherwise Alter Ego wakes
up and the next utterance is the command, transcribed with the main engine.
After the reply Alter Ego goes back to waiting for the wake phrase (the
owner's choice: no listening on after a reply). The awake window measures
silence, not time since waking: while the user is speaking the timer keeps
being pushed back, and it only runs out after a few seconds without a word.

Push to talk and hands-free share the microphone politely: the app pauses
this controller while the push-to-talk key is held, and while Alter Ego
speaks, so it does not hear itself. The exception is "interrupt by talking"
(off by default): while the reply to a hands-free request is spoken the
microphone stays open, and as soon as the user starts to speak `interrupted`
fires (the app stops the voice) and what they say becomes the next request.
With speakers instead of headphones Alter Ego may hear its own voice and
cut itself off, which is why it is opt-in.
"""

from __future__ import annotations

from enum import Enum
from typing import Callable

from PySide6.QtCore import QObject, QThread, QTimer, Signal

from .audio import AudioClip
from .controller import _PrepareWorker, _TranscribeWorker
from .recorder import MicrophoneError, MicrophoneRecorder
from .transcriber import Transcriber
from .vad import DEFAULT_SENSITIVITY, SENSITIVITY_LEVELS, UtteranceDetector
from .wake import DEFAULT_PHRASE, match_wake_phrase

MAX_QUEUED = 1  # Utterances kept while a scan is still running (the newest wins).

DEFAULT_AWAKE_S = 3.0      # seconds of silence after the wake phrase before Alter Ego stops listening
AWAKE_MESSAGE = "I'm listening... what can I do for you?"
RETRY_MESSAGE = "I didn't catch that. Could you say it again?"


class HandsFreeState(Enum):
    OFF = "off"
    WAITING = "waiting"            # listening for the wake phrase
    AWAKE = "awake"                # wake phrase heard, waiting for the command
    TRANSCRIBING = "transcribing"  # the command is being recognised


class HandsFree(QObject):
    state_changed = Signal(object)  # HandsFreeState
    status = Signal(str)            # Short text for the chat panel; "" clears it
    woke = Signal()                 # The wake phrase was heard: show Alter Ego
    listening = Signal()            # ...and it came alone, so Alter Ego now waits for the request (time to say "yes?")
    interrupted = Signal()          # The user started talking over a hands-free reply: stop the voice
    command = Signal(str)           # What the user asked for, ready to send
    failed = Signal(str)            # A problem, in words for the user; hands-free then switches itself off
    heard = Signal(str, bool)       # Every wake-scan transcript and whether it matched (for diagnostics)

    def __init__(
        self,
        recorder: MicrophoneRecorder,
        wake_transcriber: Transcriber | None = None,
        command_transcriber: Transcriber | None = None,
        phrase: str = DEFAULT_PHRASE,
        awake_s: float = DEFAULT_AWAKE_S,
        parent: QObject | None = None,
    ):
        super().__init__(parent)
        self._recorder = recorder
        self._wake_transcriber = wake_transcriber
        self._command_transcriber = command_transcriber
        self._phrase = phrase or DEFAULT_PHRASE
        self._awake_s = awake_s
        self._interrupt_by_voice = False  # Talking over a hands-free reply stops it (opt-in).
        self._watching = False            # The reply to a hands-free request is being spoken, mic open.
        self._detector = UtteranceDetector()
        self._state = HandsFreeState.OFF
        self._paused = False
        self._worker: QThread | None = None
        self._pending: list[tuple[AudioClip, Callable[[str], None]]] = []
        self._from_hands_free = False  # The reply being given answers a request made here.
        self._silence_window_s = awake_s  # How much silence ends the current awake window.

        self._awake_timer = QTimer(self)
        self._awake_timer.setSingleShot(True)
        self._awake_timer.timeout.connect(self._on_awake_timeout)

        recorder.chunk.connect(self._on_chunk)

    # ----- Properties and settings -----

    @property
    def state(self) -> HandsFreeState:
        return self._state

    @property
    def active(self) -> bool:
        return self._state is not HandsFreeState.OFF

    @property
    def phrase(self) -> str:
        return self._phrase

    def set_phrase(self, phrase: str) -> None:
        self._phrase = phrase.strip() or DEFAULT_PHRASE

    def set_interrupt_by_voice(self, enabled: bool) -> None:
        self._interrupt_by_voice = bool(enabled)
        if not enabled:
            self._watching = False

    @property
    def interruptible(self) -> bool:
        """True while Alter Ego answers a hands-free request and talking over it may stop it."""
        return (self._interrupt_by_voice and self._from_hands_free
                and self._state in (HandsFreeState.WAITING, HandsFreeState.AWAKE))

    def watch_for_interrupt(self) -> None:
        """The reply is being spoken: keep the microphone open and stop it when the user talks."""
        if not self.interruptible or self._watching:
            return
        self._watching = True
        self._detector.reset()  # Start clean: the "Yes?" or the reply's first words must not count.
        if self._paused:
            self.resume()

    def stop_watching(self) -> None:
        self._watching = False

    def set_timings(self, awake_s: float) -> None:
        self._awake_s = max(1.0, awake_s)

    def set_transcribers(self, wake: Transcriber | None, command: Transcriber | None) -> None:
        self._wake_transcriber = wake
        self._command_transcriber = command

    def set_sensitivity(self, level: str) -> None:
        """'low', 'normal' or 'high': how quiet a sound may be and still count as speech."""
        floor = SENSITIVITY_LEVELS.get(str(level).lower(), SENSITIVITY_LEVELS[DEFAULT_SENSITIVITY])
        if floor != self._detector.min_speech_rms:
            self._detector = UtteranceDetector(floor)

    @property
    def sensitivity(self) -> str:
        for name, floor in SENSITIVITY_LEVELS.items():
            if floor == self._detector.min_speech_rms:
                return name
        return "custom"

    # ----- Switching on and off -----

    def start(self) -> bool:
        """Open the microphone and wait for the wake phrase. Returns False (with `failed`) if it cannot."""
        if self.active:
            return True
        if self._wake_transcriber is None or self._command_transcriber is None:
            self.failed.emit("Hands-free needs speech recognition, which is switched off.")
            return False
        self._paused = False
        if not self._open_microphone():
            return False
        self._set_state(HandsFreeState.WAITING)
        if not self._wake_transcriber.ready:
            # Load the wake model now so the first "Hey Alter Ego" is not missed while it loads.
            self.status.emit("Loading the wake-word model...")
            worker = _PrepareWorker(self._wake_transcriber, self)
            worker.done.connect(lambda _message: self.status.emit(""))
            worker.failed.connect(self._on_failure)
            worker.finished.connect(self._on_worker_finished)
            self._worker = worker
            worker.start(QThread.Priority.LowPriority)  # Models and servers must not make the desktop sluggish.
        return True

    def stop(self) -> None:
        """Close the microphone and forget everything heard so far."""
        self._awake_timer.stop()
        self._watching = False
        self._pending.clear()
        if self._recorder.recording:
            self._recorder.stop()
        self._detector.reset()
        if self.active:
            self._set_state(HandsFreeState.OFF)
            self.status.emit("")
        worker = self._worker
        if worker is not None and worker.isRunning():
            worker.wait(5000)

    def pause(self) -> None:
        """Hand the microphone to push to talk for a moment."""
        if not self.active or self._paused:
            return
        self._paused = True
        if self._recorder.recording:
            self._recorder.stop()
        self._detector.reset()

    def resume(self) -> None:
        if not self.active or not self._paused:
            return
        self._paused = False
        if not self._open_microphone():
            self._set_state(HandsFreeState.OFF)
            return
        if self._state is HandsFreeState.AWAKE:
            # Paused while Alter Ego said "yes?": the user gets the whole window from now, not what is left.
            self._awake_timer.start(int(self._silence_window_s * 1000))

    def reply_finished(self) -> None:
        """Alter Ego has finished answering: back to waiting for the wake phrase, no listening on."""
        self._from_hands_free = False
        self._watching = False

    # ----- Audio in -----

    def _open_microphone(self) -> bool:
        try:
            self._recorder.start(stream=True)
        except MicrophoneError as error:
            self.failed.emit(f"{error} Hands-free is off until the microphone works.")
            return False
        return True

    def _on_chunk(self, clip: AudioClip) -> None:
        if not self.active or self._paused:
            return
        utterances = self._detector.feed(clip.samples)
        if self._watching and (self._detector.speaking or utterances):
            # The user talks over the reply: stop it, and treat what they say as the next request.
            self._watching = False
            self._from_hands_free = False
            self.interrupted.emit()
            self._go_awake(AWAKE_MESSAGE, self._awake_s)
        for utterance in utterances:
            self._on_utterance(utterance)
        if self._state is HandsFreeState.AWAKE and self._detector.speaking:
            # The user is talking: the silence countdown starts over once they stop.
            self._awake_timer.start(int(self._silence_window_s * 1000))

    def _on_utterance(self, clip: AudioClip) -> None:
        if self._state is HandsFreeState.WAITING:
            if self._wake_transcriber is not None:
                self._run_or_queue(self._wake_transcriber, clip, self._on_wake_text)
        elif self._state is HandsFreeState.AWAKE:
            self._awake_timer.stop()
            self._set_state(HandsFreeState.TRANSCRIBING)
            self.status.emit("Recognising...")
            if self._command_transcriber is not None:
                self._run_or_queue(self._command_transcriber, clip, self._on_command_text)

    def _run_or_queue(self, transcriber: Transcriber, clip: AudioClip, on_text: Callable[[str], None]) -> None:
        if self._worker is None:
            self._run(transcriber, clip, on_text)
            return
        # Still busy with the previous utterance: keep this one for right after, newest first.
        self._pending = self._pending[-(MAX_QUEUED - 1):] if MAX_QUEUED > 1 else []
        self._pending.append((clip, on_text))

    # ----- Recognition results (GUI thread) -----

    def _run(self, transcriber: Transcriber, clip: AudioClip, on_text: Callable[[str], None]) -> None:
        worker = _TranscribeWorker(transcriber, clip, self)
        worker.done.connect(on_text)
        worker.failed.connect(self._on_failure)
        worker.finished.connect(self._on_worker_finished)
        self._worker = worker
        worker.start(QThread.Priority.LowPriority)  # Models and servers must not make the desktop sluggish.

    def _on_wake_text(self, text: str) -> None:
        if self._state is not HandsFreeState.WAITING:
            return
        remainder = match_wake_phrase(text, self._phrase)
        self.heard.emit(text, remainder is not None)
        if remainder is None:
            return
        self.woke.emit()
        if len(remainder.split()) >= 2:
            self._deliver(remainder)  # "Hey Alter Ego, what's the time" in one breath.
        else:
            self._go_awake(AWAKE_MESSAGE, self._awake_s)
            self.listening.emit()

    def _on_command_text(self, text: str) -> None:
        if self._state is not HandsFreeState.TRANSCRIBING:
            return
        if text.strip():
            self._deliver(text.strip())
        else:
            self._go_awake(RETRY_MESSAGE, self._awake_s)

    def _on_failure(self, message: str) -> None:
        # A failing engine would fail on every utterance; switch off rather than nag.
        self.stop()
        self.failed.emit(f"{message} Hands-free is now off.")

    def _on_worker_finished(self) -> None:
        worker = self._worker
        self._worker = None
        if worker is not None:
            worker.deleteLater()
        if self._pending and self.active:
            clip, on_text = self._pending.pop(0)
            transcriber = self._command_transcriber if on_text == self._on_command_text else self._wake_transcriber
            if transcriber is not None and (self._state is not HandsFreeState.WAITING or on_text == self._on_wake_text):
                self._run(transcriber, clip, on_text)

    # ----- State -----

    def _deliver(self, text: str) -> None:
        self._from_hands_free = True
        self._set_state(HandsFreeState.WAITING)
        self.status.emit("")
        self.command.emit(text)

    def _go_awake(self, message: str, seconds: float) -> None:
        self._silence_window_s = seconds
        self._set_state(HandsFreeState.AWAKE)
        self.status.emit(message)
        self._awake_timer.start(int(seconds * 1000))

    def _on_awake_timeout(self) -> None:
        if self._state is HandsFreeState.AWAKE:
            self._set_state(HandsFreeState.WAITING)
            self.status.emit("")

    def _set_state(self, state: HandsFreeState) -> None:
        if state is not self._state:
            self._state = state
            self.state_changed.emit(state)
