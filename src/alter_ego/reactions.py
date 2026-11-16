"""Makes the character's face follow the conversation.

listening  -> surprised (attentive) while the push-to-talk key is held
thinking   -> side glance (also while speech is being recognised)
replying   -> the expression attached to the reply, for as long as it is typed out
afterwards -> back to the idle expression after a short pause

This is the only place that connects the assistant to the ExpressionManager.
"""

from __future__ import annotations

from PySide6.QtCore import QObject, QTimer

from .chat import ChatWindow
from .core.assistant import Assistant, AssistantState
from .core.conversation import Message, Role
from .expressions import Expression, ExpressionManager
from .speech.controller import ListeningState, PushToTalk
from .speech.handsfree import HandsFree, HandsFreeState

LISTENING_EXPRESSION = Expression.SURPRISED_TALK
THINKING_EXPRESSION = Expression.SIDE_TALK
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

        assistant.state_changed.connect(self._on_state_changed)
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
            self._expressions.set_expression(THINKING_EXPRESSION)

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
            self._idle_timer.stop()
            self._expressions.set_expression(message.expression)

    def _return_to_idle(self) -> None:
        self._expressions.set_expression(IDLE_EXPRESSION)
