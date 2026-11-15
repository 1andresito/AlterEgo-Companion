"""The text chat panel that opens when the character is clicked.

It shows the Conversation history, lets the user type a message, and reveals
Alter Ego's replies with a typewriter effect. It never produces replies itself:
it only calls Assistant.send() and listens to the Conversation.
"""

from __future__ import annotations

import html

from PySide6.QtCore import QPoint, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QFont, QPainter, QPen
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QTextBrowser,
    QVBoxLayout,
    QWidget,
)

from .core.assistant import Assistant, AssistantState
from .core.conversation import Conversation, Message, Role

CHAT_WIDTH = 380
CHAT_HEIGHT = 320
HEADER_HEIGHT = 30
CORNER_RADIUS = 10

# Typewriter speed for Alter Ego's replies.
TYPE_INTERVAL_MS = 30
TYPE_CHARS_PER_TICK = 2

STYLE = """
QTextBrowser {
    background: transparent;
    border: none;
    color: #d5ffbd;
    font-family: Consolas, "Courier New", monospace;
    font-size: 10pt;
}
QLineEdit {
    background: #0b1f0b;
    border: 1px solid #4cff28;
    border-radius: 4px;
    padding: 4px 6px;
    color: #e4ffd6;
    font-family: Consolas, "Courier New", monospace;
    font-size: 10pt;
    selection-background-color: #3a8a1a;
}
QLineEdit:disabled { color: #6f9a5a; border-color: #2f6d12; }
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
QPushButton#headerButton { border: none; background: transparent; padding: 0 6px; font-size: 11pt; }
QPushButton#headerButton:hover { color: #ffffff; }
QLabel#title { color: #baff85; font-family: Consolas, "Courier New", monospace; font-size: 9pt; letter-spacing: 1px; }
QScrollBar:vertical { background: transparent; width: 8px; margin: 0; }
QScrollBar::handle:vertical { background: #2f6d12; border-radius: 4px; min-height: 20px; }
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
"""


class ChatWindow(QWidget):
    # The user dragged the panel by its header, so it should stop following the character.
    dragged = Signal()
    # A reply has finished its typewriter reveal.
    typing_finished = Signal()

    def __init__(self, assistant: Assistant):
        super().__init__()
        self._assistant = assistant
        self._conversation: Conversation = assistant.conversation
        self._name = assistant.personality.name

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
        self._type_timer = QTimer(self)
        self._type_timer.setInterval(TYPE_INTERVAL_MS)
        self._type_timer.timeout.connect(self._type_step)

        self._build_ui()

        self._conversation.message_added.connect(self._on_message_added)
        self._conversation.message_updated.connect(self._on_message_updated)
        self._conversation.cleared.connect(self._on_cleared)
        assistant.state_changed.connect(lambda _state: self._update_input_state())
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
        self._input = QLineEdit()
        self._input.setPlaceholderText("Say something...")
        self._input.returnPressed.connect(self._send)
        input_row.addWidget(self._input, stretch=1)

        self._send_button = QPushButton("send")
        self._send_button.clicked.connect(self._send)
        input_row.addWidget(self._send_button)
        root.addLayout(input_row)

    # ----- Sending -----

    def _send(self) -> None:
        if self._assistant.send(self._input.text()):
            self._input.clear()

    def _clear(self) -> None:
        self._assistant.cancel()
        self._type_timer.stop()
        self._typing_message = None
        self._conversation.clear()

    def _is_busy(self) -> bool:
        return self._assistant.state is not AssistantState.IDLE or self._typing_message is not None

    def _update_input_state(self) -> None:
        busy = self._is_busy()
        self._input.setEnabled(not busy)
        self._send_button.setEnabled(not busy)
        if self._assistant.state is AssistantState.THINKING:
            self._input.setPlaceholderText(f"{self._name} is thinking...")
        elif busy:
            self._input.setPlaceholderText(f"{self._name} is talking...")
        else:
            self._input.setPlaceholderText("Say something...")
            if self.isVisible():
                self._input.setFocus()

    # ----- Rendering the history -----

    def _on_message_added(self, message: Message) -> None:
        if message.role is Role.ASSISTANT:
            self._typing_message = message
            self._typed_chars = 0
            self._type_timer.start()
            self._update_input_state()
        self._render()

    def _on_message_updated(self, message: Message) -> None:
        if not self._conversation.contains(message):
            return  # A reply that was still streaming when the chat was cleared.
        if message.role is Role.ASSISTANT and self._typing_message is None and not message.complete:
            self._typing_message = message
            self._typed_chars = 0
            self._type_timer.start()
            self._update_input_state()
        self._render()

    def _on_cleared(self) -> None:
        self._render()
        self._update_input_state()

    def _type_step(self) -> None:
        """Reveal a few more characters. Works for whole replies and for ones still streaming in."""
        message = self._typing_message
        if message is None:
            self._type_timer.stop()
            return
        if self._typed_chars < len(message.text):
            self._typed_chars = min(self._typed_chars + TYPE_CHARS_PER_TICK, len(message.text))
            self._render()
        elif message.complete:
            self._type_timer.stop()
            self._typing_message = None
            self._render()
            self._update_input_state()
            self.typing_finished.emit()
        # else: caught up with a reply that is still streaming; wait for more text.

    def _render(self) -> None:
        """Rebuild the whole history as HTML.

        Simple and good enough for a session's worth of messages. If
        conversations grow very long this can be changed to append only the
        newest block.
        """
        parts = []
        for message in self._conversation.messages:
            text = message.text
            if message is self._typing_message or not message.complete:
                text = text[: self._typed_chars] + "▌"  # left half block = cursor
            parts.append(self._format_message(message, text))

        self._view.setHtml("".join(parts))
        scrollbar = self._view.verticalScrollBar()
        scrollbar.setValue(scrollbar.maximum())

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
