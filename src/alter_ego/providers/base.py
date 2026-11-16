"""The interface every AI provider implements."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Callable, ClassVar, Iterator


@dataclass(frozen=True)
class ChatMessage:
    role: str  # "system", "user" or "assistant"
    content: str


class ProviderError(Exception):
    """Something went wrong talking to the provider.

    The message is shown to the user (in character), so write it for a human:
    say what happened and, if possible, what to do about it.
    """


class Provider(ABC):
    # Short id stored in the config file, and the label shown in menus.
    id: ClassVar[str] = ""
    label: ClassVar[str] = ""

    @abstractmethod
    def describe(self) -> str:
        """One line saying where this provider points, e.g. 'Ollama at http://...'."""

    @abstractmethod
    def list_models(self) -> list[str]:
        """Names of the models available right now. Raises ProviderError."""

    @abstractmethod
    def stream_reply(
        self,
        messages: list[ChatMessage],
        model: str,
        cancelled: Callable[[], bool],
    ) -> Iterator[str]:
        """Generate a reply, yielding pieces of text as they arrive.

        `messages` is the full conversation so far, system prompt first. A
        provider that keeps its own history (a CLI session, for example) may
        use only the last message. Check `cancelled()` between pieces and stop
        early when it returns True. Raises ProviderError.
        """

    def test_connection(self) -> str:
        """Check the provider is reachable. Returns a human-readable summary."""
        models = self.list_models()
        return f"{self.describe()}: {len(models)} model(s) available."

    def warm_up(self, progress: Callable[[str], None]) -> None:
        """The provider was chosen or the app started: get ready in the background (start a server).

        Runs on a worker thread. Reports what it is doing through `progress`
        (short text for the chat panel). Raises ProviderError.
        """

    def prepare(self, progress: Callable[[str], None]) -> None:
        """A reply is about to be requested: make the provider usable, whatever it takes.

        Runs on the reply worker thread, right before stream_reply. May take a
        long time (download a model). Reports through `progress`. Raises ProviderError.
        """
        self.warm_up(progress)

    def reset(self) -> None:
        """The conversation was cleared. Providers that keep their own session state drop it here."""
