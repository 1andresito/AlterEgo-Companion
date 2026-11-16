"""Spoken replies: turns Alter Ego's messages into speech, sentence by sentence.

    IDLE --(reply starts)--> SPEAKING --(last sentence played)--> IDLE

The Speaker watches the Conversation like the chat panel does. As a reply
streams in, each complete sentence is handed to a worker thread that runs the
text-to-speech engine; finished clips are played in order through the
SpeechPlayer. Speech starts after the first sentence, long before the reply
ends. The chat panel paces its typewriter to the audio using the
`sentence_started` signal, and `finished` tells everyone when Alter Ego has
stopped talking (the face relaxes, hands-free listens again).

Delivery follows the expression attached to the reply: shy and sad replies are
spoken a little slower, passionate ones a little faster.
"""

from __future__ import annotations

import queue
import traceback
from dataclasses import dataclass
from enum import Enum

from PySide6.QtCore import QObject, QThread, Signal

from ..core.conversation import Conversation, Message, Role
from ..expressions import Expression
from .effects import clamp_speed, crt_voice, pitch_factor, resample
from .player import PlaybackError, SpeechPlayer
from .synthesizer import Speech, Synthesizer, SynthesisError
from .text import speakable, take_sentences

DEFAULT_PITCH_SEMITONES = 2.0
DEFAULT_SPEED = 1.0

# Tempo factor per expression, multiplied with the user's speed setting.
EXPRESSION_SPEED: dict[Expression, float] = {
    Expression.HAPPY: 1.0,
    Expression.TALK: 1.0,
    Expression.PASSION_TALK: 1.08,
    Expression.SHY_TALK: 0.93,
    Expression.SIDE_TALK: 0.97,
    Expression.SAD: 0.88,
    Expression.SURPRISED_TALK: 1.05,
    Expression.SWEAT_TALK: 1.02,
}

NO_SYNTHESIZER_MESSAGE = "Spoken replies are switched off. Turn them on under Spoken replies in the menu."


class SpeakingState(Enum):
    IDLE = "idle"
    SPEAKING = "speaking"  # from the first queued sentence until the last clip has been played


@dataclass(frozen=True)
class VoiceStyle:
    """How the voice is shaped after synthesis. Read by the worker thread; replaced whole, never edited."""

    pitch_semitones: float = DEFAULT_PITCH_SEMITONES
    speed: float = DEFAULT_SPEED
    crt_effect: bool = True


@dataclass
class _Job:
    sequence: int
    text: str
    expression: Expression | None


class _SynthesisWorker(QThread):
    """One long-lived thread per synthesizer: jobs go in through a queue, clips come out through signals."""

    ready = Signal(int, object)  # sequence, Speech
    failed = Signal(int, str)    # sequence, message for the user
    status = Signal(str)

    def __init__(self, synthesizer: Synthesizer, style: VoiceStyle, parent: QObject | None = None):
        super().__init__(parent)
        self._synthesizer = synthesizer
        self.style = style
        self._jobs: queue.Queue[_Job | None] = queue.Queue()

    def submit(self, job: _Job) -> None:
        self._jobs.put(job)

    def close(self) -> None:
        self._jobs.put(None)

    def run(self) -> None:
        while True:
            job = self._jobs.get()
            if job is None:
                return
            try:
                if not self._synthesizer.ready:
                    self.status.emit("Loading my voice...")
                    self._synthesizer.prepare()
                    self.status.emit("")
                self.ready.emit(job.sequence, self._render(job))
            except SynthesisError as error:
                self.failed.emit(job.sequence, str(error))
            except Exception as error:  # noqa: BLE001 - never take the app down
                traceback.print_exc()
                self.failed.emit(job.sequence, f"something went wrong in my voice ({type(error).__name__}: {error})")

    def _render(self, job: _Job) -> Speech:
        style = self.style
        tempo = clamp_speed(style.speed) * EXPRESSION_SPEED.get(job.expression, 1.0)
        lift = pitch_factor(style.pitch_semitones) if self._synthesizer.shape_pitch else 1.0
        # Produced slower by the pitch factor, then played faster by the same factor: higher, same tempo.
        speech = self._synthesizer.synthesize(job.text, speed=tempo / lift)
        speech = resample(speech, lift)
        if style.crt_effect:
            speech = crt_voice(speech)
        return speech


class _PrepareWorker(QThread):
    done = Signal(str)
    failed = Signal(str)

    def __init__(self, synthesizer: Synthesizer, parent: QObject | None = None):
        super().__init__(parent)
        self._synthesizer = synthesizer

    def run(self) -> None:
        try:
            self.done.emit(self._synthesizer.prepare())
        except SynthesisError as error:
            self.failed.emit(str(error))
        except Exception as error:  # noqa: BLE001
            traceback.print_exc()
            self.failed.emit(f"something went wrong ({type(error).__name__}: {error})")


class Speaker(QObject):
    state_changed = Signal(object)              # SpeakingState
    status = Signal(str)                        # Short progress text for the chat panel; "" clears it
    sentence_started = Signal(object, int, float)  # (Message or None, end offset in message.text, seconds)
    finished = Signal(object)                   # Message (or None for say()): nothing more to play for it
    failed = Signal(str)                        # A problem worth telling the user about (in character)
    prepared = Signal(str)                      # Result of prepare()

    def __init__(self, player: SpeechPlayer, synthesizer: Synthesizer | None = None, parent: QObject | None = None):
        super().__init__(parent)
        self._player = player
        self._synthesizer = synthesizer
        self._style = VoiceStyle()
        self._enabled = True
        self._worker: _SynthesisWorker | None = None
        self._prepare_worker: _PrepareWorker | None = None
        self._state = SpeakingState.IDLE
        self._broken = False  # The engine failed: stay quiet instead of failing on every sentence.

        self._message: Message | None = None  # The message being spoken (None for say()).
        self._tracking = False                # Something is being spoken right now.
        self._consumed = 0                    # Characters of message.text already cut into sentences.
        self._text_done = False               # No more sentences will come for this message.
        self._sequence = 0                    # Next job number.
        self._next_to_play = 0                # Job number the player is waiting for.
        self._clips: dict[int, tuple[Speech, int]] = {}  # Finished clips waiting their turn: (speech, end offset).
        self._ends: dict[int, int] = {}       # Job number -> end offset in message.text.

        player.finished.connect(self._on_clip_finished)

    # ----- Properties and settings -----

    @property
    def state(self) -> SpeakingState:
        return self._state

    @property
    def speaking(self) -> bool:
        return self._state is SpeakingState.SPEAKING

    @property
    def current_message(self) -> Message | None:
        """The message being spoken right now, if any (the chat paces its typewriter to it)."""
        return self._message if self._tracking else None

    @property
    def enabled(self) -> bool:
        return self._enabled and self._synthesizer is not None

    @property
    def synthesizer(self) -> Synthesizer | None:
        return self._synthesizer

    @property
    def style(self) -> VoiceStyle:
        return self._style

    def set_enabled(self, enabled: bool) -> None:
        self._enabled = enabled
        if not enabled:
            self.stop()

    def set_synthesizer(self, synthesizer: Synthesizer | None) -> None:
        """Swap the engine (settings changed). Stops any speech and restarts the worker."""
        self.stop()
        self._end_worker()
        self._synthesizer = synthesizer
        self._broken = False

    def set_style(self, style: VoiceStyle) -> None:
        self._style = style
        if self._worker is not None:
            self._worker.style = style

    def attach(self, conversation: Conversation) -> None:
        conversation.message_added.connect(self._on_message_added)
        conversation.message_updated.connect(self._on_message_updated)
        conversation.cleared.connect(self.stop)

    # ----- Speaking -----

    def say(self, text: str, expression: Expression | None = None) -> bool:
        """Speak a line that is not a conversation message (for example to test the voice)."""
        if not self._can_speak():
            return False
        self.stop()
        self._begin(None)
        self._queue_text(speakable(text), final=True, expression=expression)
        return True

    def stop(self) -> None:
        """Stop talking at once and forget everything queued."""
        message, was_tracking = self._message, self._tracking
        self._clips.clear()
        self._ends.clear()
        self._message = None
        self._tracking = False
        self._next_to_play = self._sequence  # Clips from old jobs are ignored when they arrive.
        self._player.stop()  # Emits finished -> _on_clip_finished, which sees nothing to do.
        if was_tracking:
            self.finished.emit(message)
        self._set_state(SpeakingState.IDLE)
        self.status.emit("")

    def shutdown(self) -> None:
        """Stop and end the worker threads (used when quitting)."""
        self.stop()
        self._end_worker()
        worker = self._prepare_worker
        if worker is not None and worker.isRunning():
            worker.wait(5000)

    def prepare(self) -> bool:
        """Download/load the voice now. Reports through `prepared`/`failed`."""
        if self._synthesizer is None:
            self.failed.emit(NO_SYNTHESIZER_MESSAGE)
            return False
        if self._prepare_worker is not None:
            return False
        synthesizer = self._synthesizer
        if synthesizer.needs_download:
            size = getattr(synthesizer, "download_size_mb", 0)
            self.status.emit(f"Downloading my voice (about {size} MB, only once)..." if size else "Downloading my voice...")
        else:
            self.status.emit("Preparing my voice...")
        worker = _PrepareWorker(synthesizer, self)
        worker.done.connect(self._on_prepared)
        worker.failed.connect(self._on_prepare_failed)
        worker.finished.connect(self._on_prepare_finished)
        self._prepare_worker = worker
        worker.start()
        return True

    # ----- Conversation events (GUI thread) -----

    def _on_message_added(self, message: Message) -> None:
        if message.role is not Role.ASSISTANT or not self._can_speak():
            return
        self.stop()  # A new reply supersedes whatever was still being said.
        self._begin(message)
        self._feed(message)

    def _on_message_updated(self, message: Message) -> None:
        if message.role is not Role.ASSISTANT:
            return
        if self._tracking and self._message is message:
            self._feed(message)
        elif self._message is None and not message.complete and self._can_speak():
            self._begin(message)
            self._feed(message)

    def _feed(self, message: Message) -> None:
        if self._text_done:
            return
        text = message.text
        if len(text) < self._consumed:
            self._consumed = len(text)  # The final clean-up shortened the text; nothing new to say.
        new_text = text[self._consumed:]
        sentences, used = take_sentences(new_text, final=message.complete)
        self._queue_sentences(sentences, self._consumed, used, message.expression)
        self._consumed += used
        if message.complete:
            self._text_done = True
            self._check_finished()

    # ----- Queueing -----

    def _begin(self, message: Message | None) -> None:
        self._message = message
        self._tracking = True
        self._consumed = 0
        self._text_done = False
        self._set_state(SpeakingState.SPEAKING)

    def _queue_text(self, text: str, final: bool, expression: Expression | None) -> None:
        sentences, used = take_sentences(text, final=final)
        self._queue_sentences(sentences, 0, used, expression)
        if final:
            self._text_done = True
            self._check_finished()

    def _queue_sentences(self, sentences: list[str], offset: int, used: int, expression: Expression | None) -> None:
        worker = self._worker_for(self._synthesizer)
        if worker is None:
            return
        # Offsets are approximate: each sentence ends somewhere in the consumed span; the
        # chat only needs "where to have typed to by the time this clip ends".
        end = offset + used
        for index, sentence in enumerate(sentences):
            sentence = speakable(sentence)
            if not sentence:
                continue
            sequence = self._sequence
            self._sequence += 1
            self._ends[sequence] = end if index == len(sentences) - 1 else offset + _proportional_end(sentences, index, used)
            worker.submit(_Job(sequence, sentence, expression))

    def _worker_for(self, synthesizer: Synthesizer | None) -> _SynthesisWorker | None:
        if synthesizer is None:
            return None
        if self._worker is None:
            worker = _SynthesisWorker(synthesizer, self._style, self)
            worker.ready.connect(self._on_clip_ready)
            worker.failed.connect(self._on_clip_failed)
            worker.status.connect(self.status)
            worker.start()
            self._worker = worker
        return self._worker

    def _end_worker(self) -> None:
        worker = self._worker
        self._worker = None
        if worker is not None:
            worker.close()
            worker.wait(10000)
            worker.deleteLater()

    # ----- Worker and player callbacks (GUI thread) -----

    def _on_clip_ready(self, sequence: int, speech: Speech) -> None:
        if sequence < self._next_to_play:
            return  # From a reply that was stopped in the meantime.
        self._clips[sequence] = (speech, self._ends.pop(sequence, 0))
        self._play_next()

    def _on_clip_failed(self, sequence: int, message: str) -> None:
        if sequence < self._next_to_play:
            return
        print(f"Speaker: {message}")
        self._broken = True  # One failure would be followed by one per sentence; go quiet instead.
        self.stop()
        self.failed.emit(message)

    def _on_clip_finished(self) -> None:
        if not self._tracking:
            return
        self._play_next()

    def _play_next(self) -> None:
        if self._player.playing or not self._tracking:
            return
        clip = self._clips.pop(self._next_to_play, None)
        if clip is None:
            self._check_finished()
            return
        speech, end = clip
        self._next_to_play += 1
        try:
            self._player.play(speech)
        except PlaybackError as error:
            self._broken = True
            self.stop()
            self.failed.emit(str(error))
            return
        if not self._player.playing:  # An empty clip: nothing to hear, move on.
            self._play_next()
            return
        self.sentence_started.emit(self._message, end, speech.duration)

    def _check_finished(self) -> None:
        if not self._tracking or not self._text_done or self._player.playing:
            return
        if self._next_to_play < self._sequence:
            return  # Still waiting for the worker to produce a clip.
        message = self._message
        self._message = None
        self._tracking = False
        self.finished.emit(message)
        self._set_state(SpeakingState.IDLE)
        self.status.emit("")

    def _on_prepared(self, message: str) -> None:
        self._broken = False
        self.prepared.emit(message)

    def _on_prepare_failed(self, message: str) -> None:
        self._broken = True  # Otherwise the next reply would repeat that the voice is missing.
        self.failed.emit(message)

    def _on_prepare_finished(self) -> None:
        worker = self._prepare_worker
        self._prepare_worker = None
        if worker is not None:
            worker.deleteLater()
        self.status.emit("")

    # ----- Helpers -----

    def _can_speak(self) -> bool:
        if not self.enabled or self._broken:
            return False
        synthesizer = self._synthesizer
        if synthesizer is not None and synthesizer.needs_download and not synthesizer.ready:
            # Never download hundreds of megabytes behind the user's back: say so once, then keep quiet.
            self._broken = True
            size = getattr(synthesizer, "download_size_mb", 0)
            self.failed.emit(
                "I can talk out loud now, but I need to download my voice first"
                + (f" (about {size} MB, once)" if size else "")
                + ". Choose Spoken replies -> Download my voice when you're ready."
            )
            return False
        return True

    def _set_state(self, state: SpeakingState) -> None:
        if state is not self._state:
            self._state = state
            self.state_changed.emit(state)


def _proportional_end(sentences: list[str], index: int, used: int) -> int:
    """Where sentence `index` ends inside a span of `used` characters, by share of text."""
    total = sum(len(s) for s in sentences) or 1
    so_far = sum(len(s) for s in sentences[: index + 1])
    return int(used * so_far / total)
