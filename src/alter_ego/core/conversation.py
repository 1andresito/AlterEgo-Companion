"""The conversation history shared by every way of talking to Alter Ego.

This class only knows about the messages currently on screen. Saving them
across restarts is done by core/memory.py, which listens to the signals below
like any other observer.
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


@dataclass(eq=False)  # eq=False: two messages are equal only if they are the same object.
class Message:
    role: Role
    text: str
    timestamp: datetime = field(default_factory=datetime.now)
    # Which face Alter Ego makes while saying this. Only used for ASSISTANT messages.
    expression: Expression | None = None
    # False while a reply is still streaming in from the AI.
    complete: bool = True


class Conversation(QObject):
    """An ordered list of messages that announces changes through signals.

    The chat window listens to these signals instead of being told what to do
    directly, so a future voice interface can add messages to the same history
    and the chat window will update by itself.
    """

    message_added = Signal(object)    # Message
    message_updated = Signal(object)  # Message whose text/expression/complete changed
    cleared = Signal()

    def __init__(self, parent: QObject | None = None):
        super().__init__(parent)
        self._messages: list[Message] = []

    @property
    def messages(self) -> tuple[Message, ...]:
        return tuple(self._messages)

    def __len__(self) -> int:
        return len(self._messages)

    def contains(self, message: Message) -> bool:
        return any(existing is message for existing in self._messages)

    def add(self, message: Message) -> None:
        self._messages.append(message)
        self.message_added.emit(message)

    def update(
        self,
        message: Message,
        *,
        text: str | None = None,
        expression: Expression | None = None,
        complete: bool | None = None,
    ) -> None:
        """Change a message in place (used while a reply streams in)."""
        if text is not None:
            message.text = text
        if expression is not None:
            message.expression = expression
        if complete is not None:
            message.complete = complete
        self.message_updated.emit(message)

    def clear(self) -> None:
        self._messages.clear()
        self.cleared.emit()
