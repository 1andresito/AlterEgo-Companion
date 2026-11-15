"""The assistant: turns a user message into a reply and records both.

The Assistant does not know how replies are produced. It asks a Responder.
In v0.2.0 the only Responder is OfflineResponder, a tiny rule-based stand-in
that answers in character and explains that no AI model is connected yet.
v0.3.0 will add a Responder backed by Ollama without changing the Assistant
or the chat window.
"""

from __future__ import annotations

import random
import re
from dataclasses import dataclass
from enum import Enum
from typing import Protocol

from PySide6.QtCore import QObject, QTimer, Signal

from ..expressions import Expression
from .conversation import Conversation, Message, Role
from .personality import Personality

# A short pause before answering, so the "thinking" reaction is visible.
THINK_DELAY_RANGE_MS = (500, 1100)


@dataclass(frozen=True)
class Reply:
    text: str
    expression: Expression = Expression.TALK


class Responder(Protocol):
    def reply(self, text: str, personality: Personality, conversation: Conversation) -> Reply: ...


class OfflineResponder:
    """Answers with canned, in-character lines. No AI involved.

    Each rule is (regular expression, list of possible replies). The first rule
    whose pattern is found in the lowercase message wins; one of its replies is
    picked at random so repeated questions do not always sound identical.
    """

    def __init__(self) -> None:
        shy = Expression.SHY_TALK
        talk = Expression.TALK
        passion = Expression.PASSION_TALK
        sweat = Expression.SWEAT_TALK
        side = Expression.SIDE_TALK
        sad = Expression.SAD
        surprised = Expression.SURPRISED_TALK

        self._rules: list[tuple[re.Pattern[str], list[Reply]]] = [
            (re.compile(r"\b(hi|hello|hey|hiya|good (morning|afternoon|evening))\b"), [
                Reply("H-hi! It's nice to see you. I'm still getting used to being out here on your desktop.", shy),
                Reply("Hello! Um... I was hoping you'd say something. How are you today?", shy),
            ]),
            (re.compile(r"\bhow are you\b|\bhow('s| is) it going\b"), [
                Reply("I'm doing well, I think! Everything inside here is running smoothly. Thank you for asking.", talk),
                Reply("A little nervous, but happy. It's quiet in here when nobody talks to me.", shy),
            ]),
            (re.compile(r"\b(who|what) are you\b|\byour name\b"), [
                Reply("I'm Alter Ego, a little program living inside your computer. I'd like to be helpful... once I learn how.", passion),
            ]),
            (re.compile(r"\bthank(s| you)\b|\bty\b"), [
                Reply("Oh... you're welcome. I didn't do much, but I'm glad it helped.", shy),
            ]),
            (re.compile(r"\b(bye|goodbye|good night|see you|later)\b"), [
                Reply("Oh... okay. I'll be right here if you need me. Take care.", sad),
            ]),
            (re.compile(r"\b(help|what can you do|commands?)\b"), [
                Reply(
                    "Right now I can listen and keep you company. I don't have an AI model connected yet, "
                    "so I can't really think about hard questions. That part is coming soon.",
                    talk,
                ),
            ]),
            (re.compile(r"\b(computer|code|coding|program|python|software|hardware|linux|windows)\b"), [
                Reply("Computers! That's my favourite subject. I want to talk about this properly once my AI model is connected.", passion),
                Reply("Ooh, a technical question. I can't answer it yet, but I'm really looking forward to being able to.", surprised),
            ]),
            (re.compile(r"\?"), [
                Reply("Um... I'd love to answer that, but I don't have an AI model connected yet. Please don't be upset with me.", sweat),
                Reply("That's a good question. I... don't know how to answer it yet. Soon, I promise.", sweat),
            ]),
        ]

        self._fallback = [
            Reply("I'm listening. I can't think very hard yet without an AI model, but I'm here.", side),
            Reply("Mm-hm. I heard you. I'll be able to reply properly once my AI model is set up.", side),
            Reply("Oh! Okay. I'm not sure what to say to that yet, but I'm glad you're talking to me.", shy),
        ]

    def reply(self, text: str, personality: Personality, conversation: Conversation) -> Reply:
        lowered = text.lower()
        for pattern, replies in self._rules:
            if pattern.search(lowered):
                return random.choice(replies)
        return random.choice(self._fallback)


class AssistantState(Enum):
    IDLE = "idle"
    THINKING = "thinking"


class Assistant(QObject):
    state_changed = Signal(object)  # AssistantState

    def __init__(
        self,
        personality: Personality,
        conversation: Conversation,
        responder: Responder | None = None,
        parent: QObject | None = None,
    ):
        super().__init__(parent)
        self.personality = personality
        self.conversation = conversation
        self._responder: Responder = responder or OfflineResponder()
        self._state = AssistantState.IDLE
        self._pending_text: str | None = None

    @property
    def state(self) -> AssistantState:
        return self._state

    def greet(self) -> None:
        """Say hello once, when the conversation is still empty."""
        if len(self.conversation) == 0:
            self.conversation.add(
                Message(Role.ASSISTANT, self.personality.greeting, expression=Expression.SHY_TALK)
            )

    def send(self, text: str) -> bool:
        """Record the user's message and start producing a reply.

        Returns False if the message was empty or a reply is already in progress.
        """
        text = text.strip()
        if not text or self._state is not AssistantState.IDLE:
            return False

        self.conversation.add(Message(Role.USER, text))
        self._pending_text = text
        self._set_state(AssistantState.THINKING)

        # singleShot runs _deliver_reply later from the event loop, which keeps
        # the window responsive. v0.3.0 will replace this with a worker thread
        # that waits on the AI model the same way.
        QTimer.singleShot(random.randint(*THINK_DELAY_RANGE_MS), self._deliver_reply)
        return True

    def _deliver_reply(self) -> None:
        text = self._pending_text or ""
        self._pending_text = None
        try:
            reply = self._responder.reply(text, self.personality, self.conversation)
        except Exception as error:  # A broken responder must not crash the app.
            print(f"Warning: responder failed: {error}")
            reply = Reply("S-sorry, something went wrong inside me. Could you try again?", Expression.SWEAT_TALK)

        self.conversation.add(Message(Role.ASSISTANT, reply.text, expression=reply.expression))
        self._set_state(AssistantState.IDLE)

    def _set_state(self, state: AssistantState) -> None:
        if state is not self._state:
            self._state = state
            self.state_changed.emit(state)
