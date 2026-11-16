"""Push-to-talk: hold to record, release to recognise, then hand the text to the chat.

    IDLE --start()--> LISTENING --stop()--> TRANSCRIBING --(worker done)--> IDLE

Recording happens on the GUI thread (Qt delivers the audio there); the slow
part, recognition, runs on a worker thread so the desktop never freezes.
The controller does not know about keys, buttons or the chat: it just has
start()/stop() and signals, like the Assistant.
"""

from __future__ import annotations

import traceback
from enum import Enum

from PySide6.QtCore import QObject, QThread, QTimer, Signal

from .audio import AudioClip
from .recorder import MicrophoneError, MicrophoneRecorder
from .transcriber import Transcriber, TranscriptionError

MIN_DURATION_S = 0.4   # Shorter presses are taken as accidental.
MAX_DURATION_S = 60.0  # Recording stops by itself after this long.
SILENCE_PEAK = 0.005   # Below this the microphone is probably muted.

NO_TRANSCRIBER_MESSAGE = "Push to talk is switched off. Turn it on under Voice in the menu."
SILENCE_MESSAGE = "I can't hear anything at all. Is the microphone muted?"


class ListeningState(Enum):
    IDLE = "idle"
    LISTENING = "listening"          # the microphone is open
    TRANSCRIBING = "transcribing"    # the recording is being recognised


class _TranscribeWorker(QThread):
    done = Signal(str)
    failed = Signal(str)

    def __init__(self, transcriber: Transcriber, clip: AudioClip, parent: QObject | None = None):
        super().__init__(parent)
        self._transcriber = transcriber
        self._clip = clip

    def run(self) -> None:
        try:
            self.done.emit(self._transcriber.transcribe(self._clip))
        except TranscriptionError as error:
            self.failed.emit(str(error))
        except Exception as error:  # noqa: BLE001 - never take the app down
            traceback.print_exc()
            self.failed.emit(f"something went wrong while listening ({type(error).__name__}: {error})")


class _PrepareWorker(QThread):
    done = Signal(str)
    failed = Signal(str)

    def __init__(self, transcriber: Transcriber, parent: QObject | None = None):
        super().__init__(parent)
        self._transcriber = transcriber

    def run(self) -> None:
        try:
            self.done.emit(self._transcriber.prepare())
        except TranscriptionError as error:
            self.failed.emit(str(error))
        except Exception as error:  # noqa: BLE001
            traceback.print_exc()
            self.failed.emit(f"something went wrong ({type(error).__name__}: {error})")


class PushToTalk(QObject):
    state_changed = Signal(object)  # ListeningState
    status = Signal(str)            # Short progress text for the chat panel; "" when there is nothing to say.
    transcribed = Signal(str)       # Recognised text; "" when no words were heard.
    failed = Signal(str)            # A problem worth telling the user about (in character).
    prepared = Signal(str)          # Result of prepare(): the model is loaded, server reachable, ...

    def __init__(
        self,
        recorder: MicrophoneRecorder,
        transcriber: Transcriber | None = None,
        parent: QObject | None = None,
    ):
        super().__init__(parent)
        self._recorder = recorder
        self._transcriber = transcriber
        self._state = ListeningState.IDLE
        self._worker: QThread | None = None

        self._limit = QTimer(self)
        self._limit.setSingleShot(True)
        self._limit.setInterval(int(MAX_DURATION_S * 1000))
        self._limit.timeout.connect(self.stop)

    @property
    def state(self) -> ListeningState:
        return self._state

    @property
    def transcriber(self) -> Transcriber | None:
        return self._transcriber

    @property
    def available(self) -> bool:
        return self._transcriber is not None

    def set_transcriber(self, transcriber: Transcriber | None) -> None:
        self._transcriber = transcriber

    # ----- Hold / release -----

    def start(self) -> None:
        """The key or button went down: open the microphone."""
        if self._state is not ListeningState.IDLE:
            return
        if self._transcriber is None:
            self.failed.emit(NO_TRANSCRIBER_MESSAGE)
            return
        try:
            self._recorder.start()
        except MicrophoneError as error:
            self.failed.emit(str(error))
            return
        self._limit.start()
        self._set_state(ListeningState.LISTENING)
        self.status.emit("Listening... release to send")

    def stop(self) -> None:
        """The key or button came up: close the microphone and recognise what was said."""
        if self._state is not ListeningState.LISTENING:
            return
        self._limit.stop()
        clip = self._recorder.stop()
        transcriber = self._transcriber

        if clip.duration < MIN_DURATION_S or transcriber is None:
            self._finish()
            return
        if clip.peak() < SILENCE_PEAK:
            self._finish()
            self.failed.emit(SILENCE_MESSAGE)
            return

        self._set_state(ListeningState.TRANSCRIBING)
        self.status.emit("Recognising..." if transcriber.ready else "Loading the speech model (the first time can take a while)...")
        worker = _TranscribeWorker(transcriber, clip, self)
        worker.done.connect(self._on_transcribed)
        worker.failed.connect(self._on_failed)
        worker.finished.connect(self._on_worker_finished)
        self._worker = worker
        worker.start()

    def cancel(self) -> None:
        """Drop a recording in progress and wait for recognition to end (used when quitting)."""
        self._limit.stop()
        if self._state is ListeningState.LISTENING:
            self._recorder.stop()
            self._finish()
        worker = self._worker
        if worker is not None and worker.isRunning():
            worker.wait(5000)

    # ----- Preparing the engine ahead of time -----

    def prepare(self) -> bool:
        """Load the model / check the server now instead of at the first press. Reports through `prepared`/`failed`."""
        if self._transcriber is None:
            self.failed.emit(NO_TRANSCRIBER_MESSAGE)
            return False
        if self._worker is not None:
            return False
        self.status.emit("Preparing speech recognition...")
        worker = _PrepareWorker(self._transcriber, self)
        worker.done.connect(self.prepared)
        worker.failed.connect(self.failed)
        worker.finished.connect(self._on_worker_finished)
        self._worker = worker
        worker.start()
        return True

    # ----- Worker callbacks (GUI thread) -----

    def _on_transcribed(self, text: str) -> None:
        self._finish()
        self.transcribed.emit(text.strip())

    def _on_failed(self, message: str) -> None:
        self._finish()
        self.failed.emit(message)

    def _on_worker_finished(self) -> None:
        worker = self._worker
        self._worker = None
        if worker is not None:
            worker.deleteLater()
        if self._state is ListeningState.TRANSCRIBING:
            self._finish()  # Cancelled or ended without a result.
        else:
            self.status.emit("")

    def _finish(self) -> None:
        self._set_state(ListeningState.IDLE)
        self.status.emit("")

    def _set_state(self, state: ListeningState) -> None:
        if state is not self._state:
            self._state = state
            self.state_changed.emit(state)
