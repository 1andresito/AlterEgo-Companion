"""Tests for persistent memory (v0.4.0): the SQLite store, context trimming,
welcome-back greeting and the Claude Code session file.

Run from the project root with:  python -m unittest discover -s tests -v
"""

from __future__ import annotations

import sys
import tempfile
import unittest
from datetime import date, datetime, timedelta
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from PySide6.QtCore import QCoreApplication  # noqa: E402

from alter_ego.chat import day_label  # noqa: E402
from alter_ego.core.assistant import Assistant, ProviderResponder  # noqa: E402
from alter_ego.core.conversation import Conversation, Message, Role  # noqa: E402
from alter_ego.core.memory import MemoryStore  # noqa: E402
from alter_ego.core.personality import Personality  # noqa: E402
from alter_ego.expressions import Expression  # noqa: E402
from alter_ego.providers.base import ChatMessage, Provider  # noqa: E402
from alter_ego.providers.claude_code import ClaudeCodeProvider  # noqa: E402
from alter_ego.settings.config import Config  # noqa: E402

_app = QCoreApplication.instance() or QCoreApplication(sys.argv)

FAKE_CLAUDE = [sys.executable, str(Path(__file__).resolve().parent / "fake_claude.py")]


class MemoryStoreTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.path = Path(self._tmp.name) / "memory.db"
        self._open_stores: list[MemoryStore] = []

    def tearDown(self):
        for store in self._open_stores:
            try:
                store.close()
            except Exception:
                pass
        self._tmp.cleanup()

    def open_store(self) -> MemoryStore:
        store = MemoryStore(self.path)
        self._open_stores.append(store)
        return store

    def restart(self) -> tuple[MemoryStore, Conversation, int]:
        """Simulate quitting and starting again: a fresh store and conversation on the same file."""
        store = self.open_store()
        conversation = Conversation()
        restored = store.restore(conversation)
        store.attach(conversation)
        return store, conversation, restored

    def test_messages_survive_a_restart(self):
        store = self.open_store()
        conversation = Conversation()
        store.attach(conversation)

        when = datetime(2026, 11, 14, 21, 5, 7)
        conversation.add(Message(Role.USER, "remember the cake", timestamp=when))
        reply = Message(Role.ASSISTANT, "", complete=False)
        conversation.add(reply)
        conversation.update(reply, text="I w")                       # streaming: not written yet
        conversation.update(reply, text="I will.", expression=Expression.SHY_TALK, complete=True)
        store.close()

        _, restored_conversation, restored = self.restart()
        self.assertEqual(restored, 2)
        user, assistant = restored_conversation.messages
        self.assertIs(user.role, Role.USER)
        self.assertEqual(user.text, "remember the cake")
        self.assertEqual(user.timestamp, when)
        self.assertIs(assistant.role, Role.ASSISTANT)
        self.assertEqual(assistant.text, "I will.")
        self.assertIs(assistant.expression, Expression.SHY_TALK)
        self.assertTrue(assistant.complete)

    def test_clear_ends_the_conversation_and_starts_a_new_one(self):
        store = self.open_store()
        conversation = Conversation()
        store.attach(conversation)
        conversation.add(Message(Role.USER, "first chat"))
        conversation.clear()
        self.assertEqual(store.stats(), (1, 1))  # kept in the database, just not shown

        _, restored_conversation, restored = self.restart()
        self.assertEqual(restored, 0)  # a cleared chat is not restored

        restored_conversation.add(Message(Role.USER, "second chat"))
        self.assertEqual(self._open_stores[-1].stats(), (2, 2))

    def test_clearing_an_empty_chat_leaves_no_trace(self):
        store = self.open_store()
        conversation = Conversation()
        store.attach(conversation)
        conversation.clear()
        self.assertEqual(store.stats(), (0, 0))

        # A conversation holding only an unfinished, empty reply counts as empty too.
        conversation.add(Message(Role.ASSISTANT, "", complete=False))
        conversation.clear()
        self.assertEqual(store.stats(), (0, 0))

    def test_forget_all(self):
        store = self.open_store()
        conversation = Conversation()
        store.attach(conversation)
        conversation.add(Message(Role.USER, "a"))
        conversation.clear()
        conversation.add(Message(Role.USER, "b"))
        store.forget_all()
        self.assertEqual(store.stats(), (0, 0))

        conversation.clear()
        _, _, restored = self.restart()
        self.assertEqual(restored, 0)

    def test_close_flushes_a_reply_still_streaming(self):
        store = self.open_store()
        conversation = Conversation()
        store.attach(conversation)
        reply = Message(Role.ASSISTANT, "", complete=False)
        conversation.add(reply)
        conversation.update(reply, text="half a sent")
        store.close()

        _, restored_conversation, restored = self.restart()
        self.assertEqual(restored, 1)
        self.assertEqual(restored_conversation.messages[0].text, "half a sent")

    def test_detach_stops_recording_and_attach_catches_up(self):
        store = self.open_store()
        conversation = Conversation()
        store.attach(conversation)
        conversation.add(Message(Role.USER, "saved"))
        store.detach()
        self.assertFalse(store.recording)
        conversation.add(Message(Role.USER, "not saved"))
        self.assertEqual(store.stats(), (1, 1))

        store.attach(conversation)   # Re-enabled: messages added meanwhile are saved now.
        store.attach(conversation)   # Twice is harmless.
        self.assertTrue(store.recording)
        self.assertEqual(store.stats(), (1, 2))

    def test_restore_limit_keeps_the_newest_messages(self):
        store = self.open_store()
        conversation = Conversation()
        store.attach(conversation)
        for n in range(10):
            conversation.add(Message(Role.USER, f"message {n}"))
        store.close()

        store = self.open_store()
        restored_conversation = Conversation()
        self.assertEqual(store.restore(restored_conversation, limit=3), 3)
        self.assertEqual([m.text for m in restored_conversation.messages], ["message 7", "message 8", "message 9"])

        # Restored messages are known to the store: completing one updates its row instead of adding a new one.
        store.attach(restored_conversation)
        store.detach()
        self.assertEqual(store.stats(), (1, 10))

    def test_restored_conversation_continues_in_the_same_row(self):
        store = self.open_store()
        conversation = Conversation()
        store.attach(conversation)
        conversation.add(Message(Role.USER, "before restart"))
        store.close()

        store, conversation, _ = self.restart()
        conversation.add(Message(Role.USER, "after restart"))
        self.assertEqual(store.stats(), (1, 2))


class ContextLimitTests(unittest.TestCase):
    class RecordingProvider(Provider):
        id = "fake"
        label = "Fake"

        def __init__(self):
            self.last_messages: list[ChatMessage] = []

        def describe(self):
            return "fake"

        def list_models(self):
            return ["model-a"]

        def stream_reply(self, messages, model, cancelled):
            self.last_messages = messages
            yield "[happy] ok"

    def sent_history(self, context_messages, history):
        config = Config(Path("unused.json"), {"memory": {"context_messages": context_messages}})
        provider = self.RecordingProvider()
        responder = ProviderResponder(provider, config)
        list(responder.stream_reply("x", Personality.default(), history, lambda: False))
        return [m.content for m in provider.last_messages[1:]]  # skip the system prompt

    def test_only_recent_messages_are_sent(self):
        history = [Message(Role.USER, f"m{n}") for n in range(6)]
        self.assertEqual(self.sent_history(2, history), ["m4", "m5"])
        self.assertEqual(self.sent_history(0, history), [f"m{n}" for n in range(6)])
        self.assertEqual(self.sent_history("nonsense", history), [f"m{n}" for n in range(6)])

    def test_default_limit_is_thirty(self):
        config = Config(Path("unused.json"))
        self.assertEqual(ProviderResponder(self.RecordingProvider(), config).context_limit(), 30)


class WelcomeBackTests(unittest.TestCase):
    def test_greets_normally_when_empty(self):
        assistant = Assistant(Personality.default(), Conversation())
        assistant.greet()
        self.assertEqual(assistant.conversation.messages[0].text, Personality.default().greeting)

    def test_welcomes_back_after_a_long_pause_only_once(self):
        conversation = Conversation()
        conversation.add(Message(Role.USER, "see you", timestamp=datetime.now() - timedelta(hours=3)))
        assistant = Assistant(Personality.default(), conversation)
        assistant.greet()
        assistant.greet()
        self.assertEqual(len(conversation), 2)
        self.assertEqual(conversation.messages[1].text, Personality.default().return_greeting)

    def test_no_welcome_back_after_a_short_pause(self):
        conversation = Conversation()
        conversation.add(Message(Role.USER, "brb", timestamp=datetime.now() - timedelta(minutes=5)))
        assistant = Assistant(Personality.default(), conversation)
        assistant.greet()
        self.assertEqual(len(conversation), 1)

    def test_bundled_personality_has_a_return_greeting(self):
        personality = Personality.load(PROJECT_ROOT / "assets" / "personality" / "alter_ego.json")
        self.assertIn("back", personality.return_greeting.lower())


class ClaudeCodeSessionFileTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.session_file = Path(self._tmp.name) / "claude_code" / "session"

    def tearDown(self):
        self._tmp.cleanup()

    def reply(self, provider, text="hello"):
        msgs = [ChatMessage("system", "You are Alter Ego."), ChatMessage("user", text)]
        return "".join(provider.stream_reply(msgs, "default", lambda: False))

    def test_session_is_resumed_by_a_new_provider(self):
        first = ClaudeCodeProvider(command=FAKE_CLAUDE, session_file=self.session_file)
        self.assertIn("resumed=False", self.reply(first))
        self.assertTrue(self.session_file.exists())

        second = ClaudeCodeProvider(command=FAKE_CLAUDE, session_file=self.session_file)  # "after a restart"
        self.assertIn("resumed=True", self.reply(second))

        second.reset()
        self.assertFalse(self.session_file.exists())
        self.assertIn("resumed=False", self.reply(second))

    def test_lost_session_removes_the_file(self):
        provider = ClaudeCodeProvider(command=FAKE_CLAUDE, session_file=self.session_file)
        self.reply(provider, "fail-resume")
        self.assertTrue(self.session_file.exists())
        self.assertIn("resumed=False", self.reply(provider, "fail-resume"))  # retried as a new session
        self.assertTrue(self.session_file.exists())                           # ...which is saved again

    def test_garbage_in_the_file_is_ignored(self):
        self.session_file.parent.mkdir(parents=True)
        self.session_file.write_text("not a uuid", encoding="utf-8")
        provider = ClaudeCodeProvider(command=FAKE_CLAUDE, session_file=self.session_file)
        self.assertIn("resumed=False", self.reply(provider))

    def test_no_file_means_no_persistence(self):
        provider = ClaudeCodeProvider(command=FAKE_CLAUDE)
        self.reply(provider)
        self.assertFalse(self.session_file.exists())


class DayLabelTests(unittest.TestCase):
    def test_labels(self):
        today = date.today()
        self.assertEqual(day_label(today), "today")
        self.assertEqual(day_label(today - timedelta(days=1)), "yesterday")
        self.assertEqual(day_label(date(2001, 3, 5)), "Monday 5 March 2001")


if __name__ == "__main__":
    unittest.main()
