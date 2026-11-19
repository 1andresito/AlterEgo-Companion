"""The text chat panel that opens when the character is clicked.

It shows the Conversation history, lets the user type a message, and reveals
Alter Ego's replies with a typewriter effect. It never produces replies itself:
it only calls Assistant.send() and listens to the Conversation.

When replies are spoken (voice/speaker.py), the typewriter follows the voice:
each sentence is typed out over the time its audio takes, and the reply counts
as finished only when the last clip has been played.
"""

from __future__ import annotations

import html
import math
import time
from datetime import date, timedelta

from PySide6.QtCore import QPoint, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QFont, QFontMetricsF, QPainter, QPen, QTextCursor, QTextOption
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QPlainTextEdit,
    QPushButton,
    QTextBrowser,
    QVBoxLayout,
    QWidget,
)

from .core.assistant import Assistant, AssistantState
from .core.conversation import Conversation, Message, Role
from .expressions import Expression
from .speech.controller import ListeningState, PushToTalk
from .speech.handsfree import HandsFree
from .voice.speaker import Speaker

# How long a short voice hint ("I didn't catch that") stays in the input box.
HINT_MS = 3000

CHAT_WIDTH = 380
CHAT_HEIGHT = 320
HEADER_HEIGHT = 30
CORNER_RADIUS = 10

# Typewriter speed for Alter Ego's replies (when no voice is pacing it).
TYPE_INTERVAL_MS = 30
TYPE_CHARS_PER_TICK = 2.0
# Typed text runs slightly ahead of the voice, so a sentence is on screen as it is heard.
VOICE_LEAD = 0.9
# Within this many pixels of the end counts as "at the bottom": the view then follows new text.
SCROLL_SLACK_PX = 4
# The "..." shown while Alter Ego thinks: one more dot this often.
DOTS_INTERVAL_MS = 400
# Mid-reply, after this long with no new words (a web search, a slow model), the dots come back.
STALL_S = 0.8
# The input box grows with its text up to this many lines, then scrolls.
INPUT_MAX_LINES = 5
# Shown instead of "thinking" once the words are in and only the voice is still on its way.
VOICE_WAIT = "getting my voice ready"

STYLE = """
QTextBrowser {
    background: transparent;
    border: none;
    color: #d5ffbd;
    font-family: Consolas, "Courier New", monospace;
    font-size: 10pt;
}
QPlainTextEdit {
    background: #0b1f0b;
    border: 1px solid #4cff28;
    border-radius: 4px;
    padding: 4px 6px;
    color: #e4ffd6;
    font-family: Consolas, "Courier New", monospace;
    font-size: 10pt;
    selection-background-color: #3a8a1a;
}
QPlainTextEdit:disabled { color: #6f9a5a; border-color: #2f6d12; }
QPushButton {
    background: #10250d;
    border: 1px solid #8dff45;
    border-radius: 4px;
    color: #baff85;
    padding: 4px 10px;
    font-family: Consolas, "Courier New", monospace;
    font-size: 10pt;
}
QPushButton:hover { background: #1a3a14; }
QPushButton:pressed { background: #2f6d12; }
QPushButton:disabled { color: #6f9a5a; border-color: #2f6d12; }
QPushButton[stopping="true"] { color: #8fae7c; border-color: #4f7f35; background: #0d1a0b; }
QPushButton[stopping="true"]:hover { color: #e4ffd6; border-color: #8dff45; }
QPushButton#headerButton { border: none; background: transparent; padding: 0 6px; font-size: 11pt; }
QPushButton#headerButton:hover { color: #ffffff; }
QLabel#title { color: #baff85; font-family: Consolas, "Courier New", monospace; font-size: 9pt; letter-spacing: 1px; }
QScrollBar:vertical { background: transparent; width: 8px; margin: 0; }
QScrollBar::handle:vertical { background: #2f6d12; border-radius: 4px; min-height: 20px; }
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
"""


def day_label(day: date) -> str:
    """'today', 'yesterday', or something like 'Monday 10 November' (with the year if it differs)."""
    today = date.today()
    if day == today:
        return "today"
    if day == today - timedelta(days=1):
        return "yesterday"
    label = f"{day:%A} {day.day} {day:%B}"
    if day.year != today.year:
        label += f" {day.year}"
    return label


class ChatInput(QPlainTextEdit):
    """The message box: wraps long text and grows to INPUT_MAX_LINES lines, so nothing typed is hidden.

    Enter sends (the `submitted` signal); Shift+Enter starts a new line.
    """

    submitted = Signal()

    def __init__(self) -> None:
        super().__init__()
        self.setLineWrapMode(QPlainTextEdit.LineWrapMode.WidgetWidth)
        self.setWordWrapMode(QTextOption.WrapMode.WrapAtWordBoundaryOrAnywhere)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setTabChangesFocus(True)
        self.document().setDocumentMargin(1)  # The style sheet's padding is enough; one empty line looks like the old box.
        # A plain-text document counts its size in lines, wrapped lines included.
        self.document().documentLayout().documentSizeChanged.connect(lambda _size: self.fit())
        self.fit()

    def text(self) -> str:
        return self.toPlainText()

    def setText(self, text: str) -> None:
        self.setPlainText(text)
        self.moveCursor(QTextCursor.MoveOperation.End)

    def lines(self) -> int:
        return max(1, int(self.document().size().height()))

    def setPlaceholderText(self, text: str) -> None:
        if text != self.placeholderText():
            super().setPlaceholderText(text)
            self.fit()  # A long status ("Downloading my voice...") wraps: the box grows so all of it shows.

    def content_height(self) -> float:
        """How tall the text (or, in an empty box, the wrapped placeholder) really is, in pixels.

        Measured from the laid-out lines, not lines x lineSpacing: with display scaling the lines
        have fractional heights, and the rounded sum left the last line cut off.
        """
        margin = self.document().documentMargin()
        if self.document().isEmpty():
            width = max(1.0, self.viewport().width() - 2 * margin)
            bounds = QFontMetricsF(self.font()).boundingRect(
                QRectF(0, 0, width, 1e6), int(Qt.TextFlag.TextWordWrap), self.placeholderText() or " "
            )
            return bounds.height() + 2 * margin
        layout = self.document().documentLayout()
        height = 0.0
        block = self.document().firstBlock()
        while block.isValid():
            height += layout.blockBoundingRect(block).height()
            block = block.next()
        return height + 2 * margin

    def max_height(self) -> float:
        return INPUT_MAX_LINES * QFontMetricsF(self.font()).lineSpacing() + 2 * self.document().documentMargin()

    def fit(self) -> None:
        """As tall as the text (or the placeholder), between one line and INPUT_MAX_LINES."""
        frame = self.height() - self.viewport().height()  # Border and padding from the style sheet.
        if frame < 0:
            frame = 2 * self.frameWidth()  # Not laid out yet.
        content = self.content_height()
        overflow = content > self.max_height() + 0.5
        self.setFixedHeight(math.ceil(min(content, self.max_height()) + frame))
        self.setVerticalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAsNeeded if overflow else Qt.ScrollBarPolicy.ScrollBarAlwaysOff
        )
        if not overflow:
            self.verticalScrollBar().setValue(0)  # Everything fits: the first line must never be scrolled away.

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        if event.size().width() != event.oldSize().width():
            self.fit()  # A new width wraps the text differently.

    def changeEvent(self, event) -> None:
        super().changeEvent(event)
        if event.type() == event.Type.StyleChange:
            self.fit()  # The style sheet sets the padding and font.

    def keyPressEvent(self, event) -> None:
        enter = event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter)
        if enter and not event.modifiers() & Qt.KeyboardModifier.ShiftModifier:
            self.submitted.emit()
            return
        super().keyPressEvent(event)


class ChatWindow(QWidget):
    # The user dragged the panel by its header, so it should stop following the character.
    dragged = Signal()
    # A reply has finished its typewriter reveal.
    typing_finished = Signal()

    def __init__(
        self,
        assistant: Assistant,
        push_to_talk: PushToTalk | None = None,
        hands_free: HandsFree | None = None,
        speaker: Speaker | None = None,
    ):
        super().__init__()
        self._assistant = assistant
        self._speaker = speaker
        self._conversation: Conversation = assistant.conversation
        self._name = assistant.personality.name
        self._push_to_talk = push_to_talk
        # True: recognised speech goes into the input box for checking instead of being sent at once.
        self.review_before_sending = False
        self._voice_status = ""  # Shown as the input placeholder: the newest of the statuses below.
        # One status per source (the AI, the voice, the microphone, a hint), so one clearing its own
        # ("" when the model has loaded) does not wipe another still going (the voice loading).
        self._statuses: dict[str, str] = {}
        self._hint_timer = QTimer(self)
        self._hint_timer.setSingleShot(True)
        self._hint_timer.setInterval(HINT_MS)
        self._hint_timer.timeout.connect(lambda: self._set_status("hint", ""))

        self.setWindowTitle(f"{self._name} - Chat")
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setFixedSize(CHAT_WIDTH, CHAT_HEIGHT)
        self.setStyleSheet(STYLE)

        self._drag_offset: QPoint | None = None

        # Typewriter state: the message being revealed and how much is visible.
        self._typing_message: Message | None = None
        self._typed_chars = 0
        self._typed_progress = 0.0       # Fractional characters, so the voice can set any speed.
        self._type_rate = TYPE_CHARS_PER_TICK
        self._pace_target: int | None = None  # With a voice: type up to here, then wait for the next sentence.
        self._type_timer = QTimer(self)
        self._type_timer.setInterval(TYPE_INTERVAL_MS)
        self._type_timer.timeout.connect(self._type_step)
        self._last_typed_at = time.monotonic()  # When the typewriter last showed a new character.

        # The "..." while Alter Ego thinks, so a pause never looks like the app froze.
        self._dots_phase = 0
        self._dots_shown = False
        self._dots_timer = QTimer(self)
        self._dots_timer.setInterval(DOTS_INTERVAL_MS)
        self._dots_timer.timeout.connect(self._dots_step)

        self._build_ui()

        self._conversation.message_added.connect(self._on_message_added)
        self._conversation.message_updated.connect(self._on_message_updated)
        self._conversation.cleared.connect(self._on_cleared)
        assistant.state_changed.connect(self._on_assistant_state)
        assistant.thought_changed.connect(lambda _thought: self._render() if self._waiting() or self._dots_shown else None)
        assistant.status.connect(lambda text: self._set_status("assistant", text))  # "Starting Ollama...", "Downloading the AI model... 43%"
        if push_to_talk is not None:
            push_to_talk.state_changed.connect(self._on_listening_changed)
            push_to_talk.status.connect(lambda text: self._set_status("push_to_talk", text))
            push_to_talk.transcribed.connect(self._on_transcribed)
            push_to_talk.failed.connect(lambda message: self._say(message, Expression.SWEAT_TALK))
            push_to_talk.prepared.connect(lambda message: self._say(message, Expression.PASSION_TALK))
        else:
            self._talk_button.hide()
        if hands_free is not None:
            # Hands-free commands take the same path as push-to-talk text.
            hands_free.status.connect(lambda text: self._set_status("hands_free", text))
            hands_free.command.connect(self._on_transcribed)
            hands_free.failed.connect(lambda message: self._say(message, Expression.SWEAT_TALK))
        if speaker is not None:
            speaker.sentence_started.connect(self._on_sentence_started)
            speaker.finished.connect(self._on_speech_finished)
            speaker.status.connect(lambda text: self._set_status("speaker", text))
            speaker.failed.connect(lambda message: self._say(message, Expression.SWEAT_TALK))
            speaker.prepared.connect(lambda message: self._say(message, Expression.PASSION_TALK))
        self._render()
        self._update_input_state()

    # ----- Layout -----

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(12, 6, 12, 12)
        root.setSpacing(8)

        header = QHBoxLayout()
        header.setContentsMargins(0, 0, 0, 0)
        title = QLabel(f"{self._name.upper()}  //  CHAT")
        title.setObjectName("title")
        header.addWidget(title)
        header.addStretch()

        clear_button = QPushButton("clear")
        clear_button.setObjectName("headerButton")
        clear_button.setToolTip("Clear the conversation")
        clear_button.clicked.connect(self._clear)
        header.addWidget(clear_button)

        close_button = QPushButton("×")  # multiplication sign, looks like a close "x"
        close_button.setObjectName("headerButton")
        close_button.setToolTip("Hide chat")
        close_button.clicked.connect(self.hide)
        header.addWidget(close_button)
        root.addLayout(header)

        self._view = QTextBrowser()
        self._view.setOpenExternalLinks(False)
        self._view.viewport().setAutoFillBackground(False)
        root.addWidget(self._view, stretch=1)

        input_row = QHBoxLayout()
        input_row.setSpacing(6)
        input_row.setAlignment(Qt.AlignmentFlag.AlignBottom)  # The buttons stay at the bottom as the box grows.
        self._input = ChatInput()
        self._input.setPlaceholderText("Say something...")
        self._input.submitted.connect(self._send)
        input_row.addWidget(self._input, stretch=1)

        # Hold to talk. pressed/released (not clicked) so the recording lasts as long as the hold.
        self._talk_button = QPushButton("talk")
        self._talk_button.setToolTip("Hold to talk")
        self._talk_button.setAutoRepeat(False)
        self._talk_button.pressed.connect(self._talk_pressed)
        self._talk_button.released.connect(self._talk_released)
        input_row.addWidget(self._talk_button)

        # "send", or "stop" while Alter Ego thinks, types or speaks (see _update_input_state).
        self._send_button = QPushButton("send")
        self._send_button.clicked.connect(self._send_or_stop)
        input_row.addWidget(self._send_button)
        root.addLayout(input_row)

    # ----- Sending -----

    def _send(self) -> None:
        if self._is_busy():
            return  # Typed while Alter Ego answers: the text waits in the box until it's done or stopped.
        if self._assistant.send(self._input.text()):
            self._input.clear()

    def _send_or_stop(self) -> None:
        if self._is_busy():
            self.stop_reply()
        else:
            self._send()

    def stop_reply(self) -> None:
        """Stop thinking, typing and speaking at once, so the user can talk again."""
        self._assistant.stop()
        if self._speaker is not None:
            self._speaker.stop()
        self._finish_typing()
        self._render()
        self._update_input_state()
        self._input.setFocus()

    def _finish_typing(self) -> None:
        """Show the rest of the message being typed at once, as if the typewriter had typed it all."""
        message = self._typing_message
        if message is None:
            return
        self._type_timer.stop()
        self._typing_message = None
        self._pace_target = None
        self._typed_chars = len(message.text)
        self.typing_finished.emit()

    def _on_assistant_state(self, state: AssistantState) -> None:
        # A new message was sent (by voice) while the last reply was still being typed out: that
        # reply is finished, so show all of it now rather than "thinking..." next to half of it.
        if state is AssistantState.THINKING and self._typing_message is not None and self._typing_message.complete:
            self._finish_typing()
            self._render()
        self._update_input_state()

    def _clear(self) -> None:
        self._assistant.cancel()
        self._conversation.clear()  # _on_cleared stops the typewriter.

    def _is_busy(self) -> bool:
        return self._assistant.state is not AssistantState.IDLE or self._typing_message is not None

    def _update_input_state(self) -> None:
        busy = self._is_busy()
        # The box stays usable, so the next message can be written while Alter Ego answers.
        self._send_button.setText("stop" if busy else "send")
        self._send_button.setToolTip(f"Stop {self._name} and talk again" if busy else "")
        self._send_button.setProperty("stopping", busy)
        self._send_button.style().unpolish(self._send_button)  # Re-read the style sheet for "stopping".
        self._send_button.style().polish(self._send_button)
        if self._voice_status:
            self._input.setPlaceholderText(self._voice_status)
        elif self._assistant.state is AssistantState.THINKING:
            self._input.setPlaceholderText(f"{self._name} is thinking...")
        elif busy:
            self._input.setPlaceholderText(f"{self._name} is talking...")
        else:
            self._input.setPlaceholderText("Say something...")
            if self.isVisible():
                self._input.setFocus()
        self._update_dots()

    # ----- Voice -----

    def _talk_pressed(self) -> None:
        if self._push_to_talk is not None:
            self._push_to_talk.start()

    def _talk_released(self) -> None:
        if self._push_to_talk is not None:
            self._push_to_talk.stop()

    def _on_listening_changed(self, state: ListeningState) -> None:
        labels = {ListeningState.LISTENING: "● rec", ListeningState.TRANSCRIBING: "..."}
        self._talk_button.setText(labels.get(state, "talk"))

    def _set_status(self, source: str, text: str) -> None:
        """Set or clear ("") the status of one source; the newest one still set is shown."""
        if source != "hint":
            self._hint_timer.stop()
            self._statuses.pop("hint", None)
        self._statuses.pop(source, None)
        if text:
            self._statuses[source] = text  # Re-inserted last: the newest.
        self._voice_status = next(reversed(self._statuses.values()), "")
        self._update_input_state()

    def _show_hint(self, text: str) -> None:
        """A short note in the input box that clears itself."""
        self._hint_timer.stop()
        self._set_status("hint", text)
        self._hint_timer.start()

    def _on_transcribed(self, text: str) -> None:
        if not text:
            self._show_hint("I didn't catch any words. Try again?")
            return
        # Sending fails while a reply is in progress; the text then waits in the box.
        if self.review_before_sending or not self._assistant.send(text):
            self._input.setText(text)
            self._input.setFocus()

    def _say(self, text: str, expression: Expression) -> None:
        """Have Alter Ego report something (an error, a result) in the chat, in character."""
        self._conversation.add(Message(Role.ASSISTANT, text, expression=expression))

    # ----- Rendering the history -----

    def _on_message_added(self, message: Message) -> None:
        if message.role is Role.ASSISTANT:
            self._start_typing(message)
        self._render()

    def _on_message_updated(self, message: Message) -> None:
        if not self._conversation.contains(message):
            return  # A reply that was still streaming when the chat was cleared.
        if message.role is Role.ASSISTANT and self._typing_message is None and not message.complete:
            # Picked up again after another line took the typewriter: its words are already on
            # screen, so carry on from there (from the start only if the voice says it again).
            self._start_typing(message, shown=0 if self._spoken(message) else len(message.text))
        self._render()

    def _on_cleared(self) -> None:
        # The chat can be cleared from the menus too, so the typewriter is stopped here, not in _clear().
        self._type_timer.stop()
        self._typing_message = None
        self._pace_target = None
        self._render()
        self._update_input_state()

    def _start_typing(self, message: Message, shown: int = 0) -> None:
        self._typing_message = message
        self._typed_chars = shown
        self._typed_progress = float(shown)
        self._type_rate = TYPE_CHARS_PER_TICK
        self._last_typed_at = time.monotonic()
        # With a voice, wait for the first sentence to start playing before showing anything.
        self._pace_target = 0 if self._spoken(message) else None
        self._type_timer.start()
        self._update_input_state()

    def _spoken(self, message: Message) -> bool:
        return self._speaker is not None and self._speaker.current_message is message

    def _type_step(self) -> None:
        """Reveal a few more characters. Works for whole replies and for ones still streaming in."""
        message = self._typing_message
        if message is None:
            self._type_timer.stop()
            return
        limit = len(message.text)
        if self._pace_target is not None:
            if not self._spoken(message):
                self._pace_target = None  # The voice gave up (or was stopped): type on at the normal speed.
                self._type_rate = TYPE_CHARS_PER_TICK
            else:
                limit = min(limit, self._pace_target)
        if self._view.verticalScrollBar().isSliderDown():
            return  # The user is dragging the scrollbar: wait, so the text doesn't move under them.
        if self._typed_chars < limit:
            self._typed_progress = min(self._typed_progress + self._type_rate, limit)
            typed = int(self._typed_progress)
            if typed != self._typed_chars:  # A slow voice can advance less than one character per tick.
                self._typed_chars = typed
                self._last_typed_at = time.monotonic()
                self._render()
        elif message.complete and self._typed_chars >= len(message.text) and not self._spoken(message):
            self._type_timer.stop()
            self._typing_message = None
            self._pace_target = None
            self._render()
            self._update_input_state()
            self.typing_finished.emit()
        # else: caught up with a reply that is still streaming, or waiting for the voice; wait for more.

    # ----- Following the voice -----

    def _on_sentence_started(self, message: object, end: int, seconds: float) -> None:
        """A sentence of `message` is being spoken: type up to `end` over the next `seconds`."""
        if message is None or message is not self._typing_message:
            return
        end = min(max(end, self._typed_chars), len(message.text))
        self._pace_target = end
        ticks = max(1.0, seconds * VOICE_LEAD * 1000 / TYPE_INTERVAL_MS)
        self._type_rate = max(0.25, (end - self._typed_chars) / ticks)
        if self._typed_progress < self._typed_chars:
            self._typed_progress = float(self._typed_chars)

    def _on_speech_finished(self, message: object) -> None:
        """The voice has stopped (done, or interrupted): show whatever is left and finish normally."""
        if message is None or message is not self._typing_message:
            return
        self._pace_target = None
        self._type_rate = TYPE_CHARS_PER_TICK * 4 if not message.complete else max(TYPE_CHARS_PER_TICK, len(message.text) - self._typed_chars)

    # ----- The thinking dots -----

    def _update_dots(self) -> None:
        """Run the dots timer only while a reply is on its way and the panel is on screen."""
        if self.isVisible() and self._is_busy():
            if not self._dots_timer.isActive():
                self._dots_timer.start()
                if self._waiting():
                    self._render()  # Show the dots now, not one tick later.
        else:
            self._dots_timer.stop()
            if self._dots_shown:
                self._render()

    def _dots_step(self) -> None:
        self._dots_phase = (self._dots_phase + 1) % 3
        if self._dots_shown or self._waiting():
            self._render()

    def _dots(self) -> str:
        return "." * (self._dots_phase + 1)

    def _stalled(self, message: Message) -> bool:
        """Mid-reply, all the words so far are typed and no more have come for a while."""
        return (not message.complete and self._typed_chars >= len(message.text)
                and time.monotonic() - self._last_typed_at >= STALL_S)

    def _waiting(self) -> bool:
        """Should the dots be on screen right now?"""
        message = self._typing_message
        if message is not None:
            return self._typed_chars == 0 or self._stalled(message)
        return self._assistant.state is AssistantState.THINKING

    def _pending_words(self, message: Message | None) -> str:
        """What the line before any words says: "thinking", "searching the web" (Assistant.thought),
        or VOICE_WAIT once the AI is done and the words only wait for the voice."""
        if self._assistant.state is not AssistantState.THINKING and message is not None:
            voice_pending = self._spoken(message) and self._pace_target == 0
            if voice_pending and (message.complete or message.text):
                return VOICE_WAIT
        return self._assistant.thought or "thinking"

    def _format_pending(self, message: Message | None = None) -> str:
        """The line shown before any words, saying what Alter Ego is doing: "ALTER EGO > thinking...",
        "thinking some more...", "searching the web...", "getting my voice ready..."."""
        words = self._pending_words(message)
        return (
            f'<p style="margin:0 0 8px 0;">'
            f'<span style="color:#baff85; font-weight:bold;">{html.escape(self._name.upper())} &gt;</span> '
            f'<span style="color:#6f9a5a;">{html.escape(words)}{self._dots()}</span></p>'
        )

    def _render(self) -> None:
        """Rebuild the whole history as HTML.

        Simple and good enough for a session's worth of messages. If
        conversations grow very long this can be changed to append only the
        newest block.
        """
        messages = self._conversation.messages
        # With memory on, the history can span days; a divider marks where each day starts.
        show_days = len({message.timestamp.date() for message in messages}) > 1
        previous_day: date | None = None

        parts = []
        dots_shown = False
        for message in messages:
            day = message.timestamp.date()
            if show_days and day != previous_day:
                previous_day = day
                parts.append(self._format_divider(day_label(day)))
            text = message.text
            if message is self._typing_message and self._typed_chars == 0 and self._is_busy():
                parts.append(self._format_pending(message))  # Nothing typed yet (waiting for the voice): the dots.
                dots_shown = True
                continue
            if message is self._typing_message:
                tail = ""
                if self._stalled(message):
                    doing = self._assistant.thought  # Mid-reply, a tool at work: "(searching the web...)".
                    tail = f" ({doing}{self._dots()})" if doing else f" {self._dots()}"
                    dots_shown = True
                text = text[: self._typed_chars] + tail + "▌"  # left half block = cursor
            elif not message.complete:
                # Still streaming while another line has the typewriter: all of it so far, never cut
                # to the other line's progress.
                text += "▌"
            parts.append(self._format_message(message, text))
        if self._typing_message is None and self._assistant.state is AssistantState.THINKING:
            parts.append(self._format_pending())
            dots_shown = True
        self._dots_shown = dots_shown

        # Follow the newest text only while the user is at the bottom: someone who scrolled up to
        # read keeps their place (rebuilding the document used to throw them back down every tick).
        scrollbar = self._view.verticalScrollBar()
        at_bottom = scrollbar.value() >= scrollbar.maximum() - SCROLL_SLACK_PX
        kept = scrollbar.value()
        self._view.setHtml("".join(parts))
        scrollbar.setValue(scrollbar.maximum() if at_bottom else min(kept, scrollbar.maximum()))

    def _format_message(self, message: Message, text: str) -> str:
        body = html.escape(text).replace("\n", "<br>")
        if message.role is Role.USER:
            speaker, color = "YOU", "#8dff45"
        else:
            speaker, color = self._name.upper(), "#baff85"
        return (
            f'<p style="margin:0 0 8px 0;">'
            f'<span style="color:{color}; font-weight:bold;">{speaker} &gt;</span> {body}</p>'
        )

    @staticmethod
    def _format_divider(label: str) -> str:
        return (
            '<p style="margin:4px 0 8px 0; color:#4f8f30; text-align:center;">'
            f"── {html.escape(label)} ──</p>"
        )

    # ----- Painting the CRT panel -----

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        panel = QRectF(self.rect()).adjusted(1.5, 1.5, -1.5, -1.5)
        painter.setPen(QPen(QColor("#4cff28"), 2))
        painter.setBrush(QColor(7, 18, 7, 236))
        painter.drawRoundedRect(panel, CORNER_RADIUS, CORNER_RADIUS)

        # Faint scanlines behind the (transparent) text area.
        painter.save()
        painter.setClipRect(panel.adjusted(2, HEADER_HEIGHT, -2, -2))
        painter.setPen(QPen(QColor(120, 255, 90, 14), 1))
        top = int(panel.top()) + HEADER_HEIGHT
        for y in range(top, int(panel.bottom()), 3):
            painter.drawLine(int(panel.left()), y, int(panel.right()), y)
        painter.restore()

        # Thin divider under the header.
        painter.setPen(QPen(QColor("#2f6d12"), 1))
        y = int(panel.top()) + HEADER_HEIGHT
        painter.drawLine(int(panel.left()) + 10, y, int(panel.right()) - 10, y)
        painter.end()

    # ----- Window behaviour -----

    def showEvent(self, event) -> None:
        super().showEvent(event)
        self._input.setFocus()
        self._update_dots()
        # Open at the newest message, not the top of a long remembered history. After this event, once
        # the layout has its real size: before that the scroll range is not known yet.
        QTimer.singleShot(0, self.scroll_to_latest)

    def scroll_to_latest(self) -> None:
        bar = self._view.verticalScrollBar()
        bar.setValue(bar.maximum())

    def hideEvent(self, event) -> None:
        super().hideEvent(event)
        self._dots_timer.stop()  # Nothing to animate off screen.

    def keyPressEvent(self, event) -> None:
        if event.key() == Qt.Key.Key_Escape:
            self.hide()
        else:
            super().keyPressEvent(event)

    def mousePressEvent(self, event) -> None:
        # Only the header strip drags the panel; the rest is normal widgets.
        if event.button() == Qt.MouseButton.LeftButton and event.position().y() < HEADER_HEIGHT:
            self._drag_offset = event.globalPosition().toPoint() - self.frameGeometry().topLeft()
            event.accept()

    def mouseMoveEvent(self, event) -> None:
        if self._drag_offset is not None and event.buttons() & Qt.MouseButton.LeftButton:
            self.move(event.globalPosition().toPoint() - self._drag_offset)
            self.dragged.emit()
            event.accept()

    def mouseReleaseEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self._drag_offset = None
            event.accept()
