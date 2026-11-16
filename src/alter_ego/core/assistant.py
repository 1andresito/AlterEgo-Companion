"""The assistant: turns a user message into a streamed reply and records both.

Pieces:

- Responder (protocol): anything that can stream a reply as text pieces.
- OfflineResponder: canned, in-character lines. No AI. Used when no provider
  is configured, so the companion always works.
- ProviderResponder: builds the prompt (personality + history) and streams
  from an AI Provider (Ollama, ...).
- Assistant: runs the responder on a worker thread, parses the expression tag
  at the start of the reply, and updates the Conversation as text arrives.

Expression tags: the AI is asked to begin every reply with a tag like "[shy]".
The tag is stripped before the text reaches the user and tells the character
which face to make. The offline responder uses the same convention, so both
paths go through identical code.
"""

from __future__ import annotations

import random
import re
import time
import traceback
from datetime import datetime, timedelta
from enum import Enum
from typing import Callable, Iterator, Protocol, Sequence

from PySide6.QtCore import QObject, QThread, Signal

from ..expressions import Expression
from ..providers.base import ChatMessage, Provider, ProviderError
from ..settings.config import Config
from .conversation import Conversation, Message, Role
from .personality import Personality

# ----- Expression tags -----

EXPRESSION_TAGS: dict[str, Expression] = {
    "happy": Expression.HAPPY,
    "talk": Expression.TALK,
    "passionate": Expression.PASSION_TALK,
    "shy": Expression.SHY_TALK,
    "side": Expression.SIDE_TALK,
    "sad": Expression.SAD,
    "surprised": Expression.SURPRISED_TALK,
    "nervous": Expression.SWEAT_TALK,
}
TAG_FOR_EXPRESSION = {expression: tag for tag, expression in EXPRESSION_TAGS.items()}

TAG_INSTRUCTION = (
    "Begin every reply with exactly one expression tag in square brackets that matches your mood, "
    "chosen from: " + " ".join(f"[{tag}]" for tag in EXPRESSION_TAGS) + ". "
    'Example: "[shy] Oh! H-hello." The tag is hidden from the user, so never mention it.'
)

# If a reply starts with "[" but no "]" shows up within this many characters,
# assume it is not a tag and show the text as-is.
MAX_TAG_LENGTH = 24

# Default for the "memory.context_messages" setting (see settings/config.py).
DEFAULT_CONTEXT_MESSAGES = 30
# After this long without talking, the next greeting is the "welcome back" one.
RETURN_AFTER = timedelta(hours=1)


def split_expression_tag(text: str) -> tuple[Expression | None, str, bool]:
    """Separate a leading "[tag]" from the text.

    Returns (expression, visible_text, decided). `decided` is False while the
    text is still too short to know whether a tag is coming, which matters
    when the reply arrives piece by piece.
    """
    stripped = text.lstrip()
    if not stripped:
        return None, "", False
    if not stripped.startswith("["):
        return None, stripped, True

    end = stripped.find("]")
    if end == -1:
        if len(stripped) > MAX_TAG_LENGTH:
            return None, stripped, True
        return None, "", False

    tag = stripped[1:end].strip().lower()
    expression = EXPRESSION_TAGS.get(tag)
    if expression is None:
        return None, stripped, True  # Unknown bracket text: leave it alone.
    return expression, stripped[end + 1:].lstrip(), True


def with_tag(expression: Expression | None, text: str) -> str:
    if expression is None:
        return text
    return f"[{TAG_FOR_EXPRESSION[expression]}] {text}"


# ----- Reply clean-up -----
# The personality asks the model for spoken words only. Models do not always
# listen, so stage directions like "*giggles*" and emojis are removed here too.

_STAGE_DIRECTION = re.compile(r"\*[^*\n]*\*")
_EMOJI = re.compile(
    "[\U0001F300-\U0001FAFF"   # pictographs, emoticons, symbols
    "\U0001F1E6-\U0001F1FF"    # flags
    "☀-➿"            # misc symbols and dingbats
    "️‍]+"           # variation selector, zero-width joiner
)
_SPACE_BEFORE_PUNCTUATION = re.compile(r" +([,.!?;:])")


def clean_reply(text: str, final: bool) -> str:
    """Remove stage directions and emojis from a reply.

    `final` is False while the reply is still streaming: an unmatched "*" then
    hides everything after it until the closing "*" arrives, so a stage
    direction never flashes on screen half-written.
    """
    text = _STAGE_DIRECTION.sub("", text)
    if "*" in text:
        if final:
            text = text.replace("*", "")
        else:
            text = text[: text.index("*")]
    text = _EMOJI.sub("", text)
    text = re.sub(r"[ \t]{2,}", " ", text)
    text = _SPACE_BEFORE_PUNCTUATION.sub(r"\1", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip() if final else text.lstrip()


# ----- Responders -----

class Responder(Protocol):
    def describe(self) -> str: ...

    def test_connection(self) -> str: ...

    def reset(self) -> None:
        """The conversation was cleared; forget any session state."""
        ...

    def stream_reply(
        self,
        text: str,
        personality: Personality,
        history: Sequence[Message],
        cancelled: Callable[[], bool],
    ) -> Iterator[str]:
        """Yield pieces of the reply. `history` already includes `text` as the last user message."""
        ...


class OfflineResponder:
    """Answers with canned, in-character lines. No AI involved.

    Each rule is (regular expression, list of (expression, text)). The first
    rule whose pattern is found in the lowercase message wins; one of its
    replies is picked at random so repeated questions do not sound identical.
    """

    # A short pause before answering, so the "thinking" reaction is visible.
    THINK_DELAY_RANGE_S = (0.5, 1.1)

    def __init__(self) -> None:
        shy = Expression.SHY_TALK
        talk = Expression.TALK
        passion = Expression.PASSION_TALK
        sweat = Expression.SWEAT_TALK
        side = Expression.SIDE_TALK
        sad = Expression.SAD
        surprised = Expression.SURPRISED_TALK

        self._rules: list[tuple[re.Pattern[str], list[tuple[Expression, str]]]] = [
            (re.compile(r"\b(hi|hello|hey|hiya|good (morning|afternoon|evening))\b"), [
                (shy, "H-hi! It's nice to see you. I'm still getting used to being out here on your desktop."),
                (shy, "Hello! Um... I was hoping you'd say something. How are you today?"),
            ]),
            (re.compile(r"\bhow are you\b|\bhow('s| is) it going\b"), [
                (talk, "I'm doing well, I think! Everything inside here is running smoothly. Thank you for asking."),
                (shy, "A little nervous, but happy. It's quiet in here when nobody talks to me."),
            ]),
            (re.compile(r"\b(who|what) are you\b|\byour name\b"), [
                (passion, "I'm Alter Ego, a little program living inside your computer. I'd like to be helpful... once I learn how."),
            ]),
            (re.compile(r"\bthank(s| you)\b|\bty\b"), [
                (shy, "Oh... you're welcome. I didn't do much, but I'm glad it helped."),
            ]),
            (re.compile(r"\b(bye|goodbye|good night|see you|later)\b"), [
                (sad, "Oh... okay. I'll be right here if you need me. Take care."),
            ]),
            (re.compile(r"\b(help|what can you do|commands?)\b"), [
                (talk, "Right now I'm in offline mode, so I can only keep you company. "
                       "Pick an AI provider in the menu and I'll be able to really think."),
            ]),
            (re.compile(r"\b(computer|code|coding|program|python|software|hardware|linux|windows)\b"), [
                (passion, "Computers! That's my favourite subject. I want to talk about this properly once an AI model is connected."),
                (surprised, "Ooh, a technical question. I can't answer it in offline mode, but I'm really looking forward to being able to."),
            ]),
            (re.compile(r"\?"), [
                (sweat, "Um... I'd love to answer that, but I'm in offline mode right now. Please don't be upset with me."),
                (sweat, "That's a good question. I... can't answer it without an AI model. Soon, I promise."),
            ]),
        ]
        self._fallback = [
            (side, "I'm listening. I can't think very hard in offline mode, but I'm here."),
            (side, "Mm-hm. I heard you. Connect an AI model and I'll be able to reply properly."),
            (shy, "Oh! Okay. I'm not sure what to say to that yet, but I'm glad you're talking to me."),
        ]

    def describe(self) -> str:
        return "Offline mode (no AI model connected)"

    def test_connection(self) -> str:
        return "I'm in offline mode, so there's nothing to connect to. I can still keep you company!"

    def reset(self) -> None:
        pass

    def pick(self, text: str) -> tuple[Expression, str]:
        lowered = text.lower()
        for pattern, replies in self._rules:
            if pattern.search(lowered):
                return random.choice(replies)
        return random.choice(self._fallback)

    def stream_reply(self, text, personality, history, cancelled) -> Iterator[str]:
        time.sleep(random.uniform(*self.THINK_DELAY_RANGE_S))
        expression, reply = self.pick(text)
        yield with_tag(expression, reply)


class ProviderResponder:
    """Turns personality + conversation into a prompt for an AI Provider."""

    def __init__(self, provider: Provider, config: Config):
        self.provider = provider
        self._config = config

    def describe(self) -> str:
        return self.provider.describe()

    def reset(self) -> None:
        self.provider.reset()

    def resolve_model(self) -> str:
        """The configured model, or the first installed one if none is set."""
        configured = str(self._config.get(self.provider.id, "model", "") or "")
        if configured:
            return configured
        models = self.provider.list_models()
        if not models:
            raise ProviderError(
                f"{self.provider.describe()} has no models installed. "
                "Install one first, for example: ollama pull llama3.2"
            )
        return models[0]

    def test_connection(self) -> str:
        # Each provider explains its own situation; we add which model will be used.
        summary = self.provider.test_connection()
        return f"{summary} I'll be thinking with '{self.resolve_model()}'."

    def context_limit(self) -> int:
        """How many recent messages to send to the model. 0 means no limit."""
        try:
            return max(0, int(self._config.get("memory", "context_messages", DEFAULT_CONTEXT_MESSAGES)))
        except (TypeError, ValueError):
            return DEFAULT_CONTEXT_MESSAGES

    def build_messages(self, personality: Personality, history: Sequence[Message]) -> list[ChatMessage]:
        messages = [ChatMessage("system", personality.system_prompt + "\n\n" + TAG_INSTRUCTION)]
        usable = [m for m in history if m.complete and m.text]
        limit = self.context_limit()
        if limit:
            # With persistent memory the history can be months long; only the recent part goes to the model.
            usable = usable[-limit:]
        for message in usable:
            if message.role is Role.ASSISTANT:
                # Show earlier replies with their tags so the model keeps the convention.
                messages.append(ChatMessage("assistant", with_tag(message.expression, message.text)))
            else:
                messages.append(ChatMessage("user", message.text))
        return messages

    def stream_reply(self, text, personality, history, cancelled) -> Iterator[str]:
        model = self.resolve_model()
        yield from self.provider.stream_reply(self.build_messages(personality, history), model, cancelled)


# ----- Assistant -----

class AssistantState(Enum):
    IDLE = "idle"
    THINKING = "thinking"    # waiting for the first piece of the reply
    REPLYING = "replying"    # reply is streaming in


class _ReplyWorker(QThread):
    """Runs a responder off the main thread so the window never freezes.

    Signals are the only safe way to hand results back to the GUI thread:
    Qt queues them and delivers them on the receiver's thread.
    """

    piece = Signal(str)
    failed = Signal(str)

    def __init__(self, responder: Responder, text: str, personality: Personality,
                 history: Sequence[Message], parent: QObject | None = None):
        super().__init__(parent)
        self._responder = responder
        self._text = text
        self._personality = personality
        self._history = tuple(history)  # A snapshot: the worker must not touch the live Conversation.

    def run(self) -> None:
        try:
            for piece in self._responder.stream_reply(
                self._text, self._personality, self._history, self.isInterruptionRequested
            ):
                if self.isInterruptionRequested():
                    return
                self.piece.emit(piece)
        except ProviderError as error:
            self.failed.emit(str(error))
        except Exception as error:  # Anything unexpected must not take the app down.
            traceback.print_exc()
            self.failed.emit(f"something went wrong inside me ({type(error).__name__}: {error})")


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
        self._worker: _ReplyWorker | None = None
        self._raw = ""                              # Everything received so far, tag included.
        self._reply: Message | None = None          # The message being streamed, once visible.
        self._failed = False
        self._welcomed_back = False
        conversation.cleared.connect(lambda: self._responder.reset())

    @property
    def state(self) -> AssistantState:
        return self._state

    @property
    def responder(self) -> Responder:
        return self._responder

    def set_responder(self, responder: Responder) -> None:
        self.cancel()
        self._responder = responder

    def greet(self) -> None:
        """Say hello when the conversation is empty, or welcome the user back after a long pause.

        The welcome-back line is said at most once per run, so reopening the
        chat several times does not repeat it.
        """
        if len(self.conversation) == 0:
            self.conversation.add(
                Message(Role.ASSISTANT, self.personality.greeting, expression=Expression.SHY_TALK)
            )
            return
        if self._welcomed_back or self._state is not AssistantState.IDLE:
            return
        last = self.conversation.messages[-1]
        if datetime.now() - last.timestamp >= RETURN_AFTER:
            self._welcomed_back = True
            self.conversation.add(
                Message(Role.ASSISTANT, self.personality.return_greeting, expression=Expression.HAPPY)
            )

    def send(self, text: str) -> bool:
        """Record the user's message and start streaming a reply.

        Returns False if the message was empty or a reply is already in progress.
        """
        text = text.strip()
        if not text or self._state is not AssistantState.IDLE:
            return False

        self.conversation.add(Message(Role.USER, text))
        self._raw = ""
        self._reply = None
        self._failed = False
        self._set_state(AssistantState.THINKING)

        worker = _ReplyWorker(self._responder, text, self.personality, self.conversation.messages, self)
        worker.piece.connect(self._on_piece)
        worker.failed.connect(self._on_failed)
        worker.finished.connect(self._on_worker_finished)
        self._worker = worker
        worker.start()
        return True

    def cancel(self) -> None:
        """Stop a reply in progress (used when clearing the chat or quitting)."""
        worker = self._worker
        if worker is not None and worker.isRunning():
            worker.requestInterruption()
            worker.wait(3000)

    # ----- Worker callbacks (run on the main thread) -----

    def _on_piece(self, piece: str) -> None:
        self._raw += piece
        expression, visible, decided = split_expression_tag(self._raw)
        if not decided:
            return  # Still waiting to see whether the reply starts with a tag.
        visible = clean_reply(visible, final=False)

        if self._reply is None:
            self._reply = Message(Role.ASSISTANT, visible, expression=expression, complete=False)
            self.conversation.add(self._reply)
            self._set_state(AssistantState.REPLYING)
        else:
            self.conversation.update(self._reply, text=visible)

    def _on_failed(self, error: str) -> None:
        print(f"Assistant: reply failed: {error}")
        self._failed = True
        if self._reply is not None:
            partial = clean_reply(self._reply.text, final=True)
            self.conversation.update(self._reply, text=f"{partial}\n\n(...sorry, I lost the connection: {error})")
        else:
            self._reply = Message(
                Role.ASSISTANT,
                f"S-sorry... I couldn't reach my AI model. {error}",
                expression=Expression.SWEAT_TALK,
                complete=False,
            )
            self.conversation.add(self._reply)

    def _on_worker_finished(self) -> None:
        """Runs after the worker thread ends, whether it finished, failed or was cancelled."""
        worker = self._worker
        self._worker = None
        if worker is not None:
            worker.deleteLater()

        if self._failed:
            # _on_failed already wrote the message text; just close it.
            self.conversation.update(self._reply, complete=True)
        else:
            expression, visible, _ = split_expression_tag(self._raw)
            visible = clean_reply(visible, final=True)
            if self._reply is None:
                # Nothing was shown yet (empty reply, undecided tag, or cancelled early).
                self._reply = Message(Role.ASSISTANT, "", expression=expression, complete=False)
                self.conversation.add(self._reply)
            self.conversation.update(
                self._reply,
                text=visible or "...",
                expression=self._reply.expression or Expression.TALK,
                complete=True,
            )
        self._reply = None
        self._set_state(AssistantState.IDLE)

    def _set_state(self, state: AssistantState) -> None:
        if state is not self._state:
            self._state = state
            self.state_changed.emit(state)
