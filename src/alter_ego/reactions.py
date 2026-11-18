"""Makes the character's face follow the conversation.

listening  -> surprised (attentive) while the push-to-talk key is held
thinking   -> a face for what it is thinking about (Assistant.thought): a side glance
              to start, shy when thinking some more, nervous when thinking really hard,
              eager while it searches or writes, focused while it reads, "oh!" when it
              looks at what it found. Each change comes from something happening, not a clock.
              (A side glance also while speech is being recognised.)
replying   -> the expression attached to the reply, for as long as it is typed out
afterwards -> back to the idle expression after a short pause

This is the only place that connects the assistant to the ExpressionManager.
"""

from __future__ import annotations

from PySide6.QtCore import QObject, QTimer

from .chat import ChatWindow
from .core.assistant import (
    LOOKING_AT_RESULTS, THINKING, THINKING_HARD, THINKING_MORE, Assistant, AssistantState,
)
from .core.conversation import Message, Role
from .expressions import Expression, ExpressionManager
from .speech.controller import ListeningState, PushToTalk
from .speech.handsfree import HandsFree, HandsFreeState

LISTENING_EXPRESSION = Expression.SURPRISED_TALK
THINKING_EXPRESSION = Expression.SIDE_TALK
# Faces for what Alter Ego is thinking about. Tool thoughts come from core/tools.py progress_text
# ("searching the web", "reading notes.txt"), so they are matched by their first word.
THOUGHT_FACES = {
    THINKING: Expression.SIDE_TALK,          # glancing aside, working it out
    THINKING_MORE: Expression.SHY_TALK,      # eyes down, pondering
    THINKING_HARD: Expression.SWEAT_TALK,    # a little nervous it's taking so long
    LOOKING_AT_RESULTS: Expression.SURPRISED_TALK,  # "oh!", something came back
}
ACTIVITY_FACES = {
    "searching": Expression.PASSION_TALK,    # computers and the internet light it up
    "writing": Expression.PASSION_TALK,
    "making": Expression.PASSION_TALK,
    "reading": Expression.TALK,              # focused
    "looking": Expression.TALK,
}


def face_for(thought: str) -> Expression:
    """The face for a thought; anything unknown (starting Ollama, downloading) gets the side glance."""
    if thought in THOUGHT_FACES:
        return THOUGHT_FACES[thought]
    first = thought.split(" ", 1)[0].lower() if thought else ""
    return ACTIVITY_FACES.get(first, THINKING_EXPRESSION)
IDLE_EXPRESSION = Expression.HAPPY
# How long Alter Ego keeps its reply face after finishing talking.
RETURN_TO_IDLE_MS = 4000


class CharacterReactions(QObject):
    def __init__(
        self,
        expressions: ExpressionManager,
        assistant: Assistant,
        chat: ChatWindow,
        push_to_talk: PushToTalk | None = None,
        hands_free: HandsFree | None = None,
        parent: QObject | None = None,
    ):
        super().__init__(parent)
        self._expressions = expressions
        self._assistant = assistant

        self._idle_timer = QTimer(self)
        self._idle_timer.setSingleShot(True)
        self._idle_timer.setInterval(RETURN_TO_IDLE_MS)
        self._idle_timer.timeout.connect(self._return_to_idle)

        self._thinking = False  # Thinking with no words yet: a reply that ends now never relaxed the face.

        assistant.state_changed.connect(self._on_state_changed)
        assistant.thought_changed.connect(self._on_thought_changed)
        assistant.conversation.message_added.connect(self._on_message_changed)
        assistant.conversation.message_updated.connect(self._on_message_changed)
        chat.typing_finished.connect(self._idle_timer.start)
        if push_to_talk is not None:
            push_to_talk.state_changed.connect(self._on_listening_changed)
        if hands_free is not None:
            hands_free.state_changed.connect(self._on_hands_free_changed)

    def _on_state_changed(self, state: AssistantState) -> None:
        if state is AssistantState.THINKING:
            self._idle_timer.stop()
            self._thinking = True
            self._expressions.set_expression(face_for(self._assistant.thought or THINKING))
        else:
            was_thinking, self._thinking = self._thinking, False
            if state is AssistantState.IDLE and was_thinking:
                self._idle_timer.start()  # Stopped (or failed) before any words: relax again after a moment.

    def _on_thought_changed(self, thought: str) -> None:
        # Before the words, and mid-reply while a tool works; "" means the words carry on (their own face).
        if thought:
            self._idle_timer.stop()
            self._expressions.set_expression(face_for(thought))

    def _on_listening_changed(self, state: ListeningState) -> None:
        if state is ListeningState.LISTENING:
            self._idle_timer.stop()
            self._expressions.set_expression(LISTENING_EXPRESSION)
        elif state is ListeningState.TRANSCRIBING:
            self._idle_timer.stop()
            self._expressions.set_expression(THINKING_EXPRESSION)
        elif self._assistant.state is AssistantState.IDLE:
            self._idle_timer.start()  # Nothing recognised or sent: relax again after a moment.

    def _on_hands_free_changed(self, state: HandsFreeState) -> None:
        # WAITING (for the wake phrase) looks like idle: Alter Ego should not stare at the user all day.
        if state is HandsFreeState.AWAKE:
            self._idle_timer.stop()
            self._expressions.set_expression(LISTENING_EXPRESSION)
        elif state is HandsFreeState.TRANSCRIBING:
            self._idle_timer.stop()
            self._expressions.set_expression(THINKING_EXPRESSION)
        elif self._assistant.state is AssistantState.IDLE:
            self._idle_timer.start()

    def _on_message_changed(self, message: Message) -> None:
        # The expression may only become known part-way through a streamed reply.
        if message.role is Role.ASSISTANT and message.expression is not None:
            self._thinking = False  # Words (or an error) arrived: the thinking is over.
            self._idle_timer.stop()
            self._expressions.set_expression(message.expression)

    def _return_to_idle(self) -> None:
        self._expressions.set_expression(IDLE_EXPRESSION)
