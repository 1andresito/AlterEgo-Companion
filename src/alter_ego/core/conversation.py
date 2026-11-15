"""In-memory conversation history shared by every way of talking to Alter Ego.

v0.2.0 keeps messages only while the app runs. Persistence (SQLite) arrives in
v0.6.0 and will plug in underneath this class.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum

from PySide6.QtCore import QObject, Signal

from ..expressions import Expression


class Role(Enum):
    USER = "user"
    ASSISTANT = "assistant"


@dataclass
class Message:
    role: Role
    text: str
    timestamp: datetime = field(default_factory=datetime.now)
    # Which face Alter Ego makes while saying this. Only used for ASSISTANT messages.
    expression: Expression | None = None


class Conversation(QObject):
    """An ordered list of messages that announces changes through signals.

    The chat window listens to these signals instead of being told what to do
    directly, so a future voice interface can add messages to the same history
    and the chat window will update by itself.
    """

    message_added = Signal(object)  # Message
    cleared = Signal()

    def __init__(self, parent: QObject | None = None):
        super().__init__(parent)
        self._messages: list[Message] = []

    @property
    def messages(self) -> tuple[Message, ...]:
        return tuple(self._messages)

    def __len__(self) -> int:
        return len(self._messages)

    def add(self, message: Message) -> None:
        self._messages.append(message)
        self.message_added.emit(message)

    def clear(self) -> None:
        self._messages.clear()
        self.cleared.emit()
