"""Tests for the non-visual core: personality, conversation, assistant.

Run from the project root with:  python -m unittest
"""

from __future__ import annotations

import sys
import time
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from PySide6.QtCore import QCoreApplication  # noqa: E402

from alter_ego.core.assistant import Assistant, AssistantState, OfflineResponder, Reply  # noqa: E402
from alter_ego.core.conversation import Conversation, Message, Role  # noqa: E402
from alter_ego.core.personality import Personality  # noqa: E402
from alter_ego.expressions import Expression  # noqa: E402

PERSONALITY_FILE = PROJECT_ROOT / "assets" / "personality" / "alter_ego.json"

# Signals and QTimer need an application object; one per test process is enough.
_app = QCoreApplication.instance() or QCoreApplication(sys.argv)


def process_events_until(condition, timeout_s: float = 3.0) -> bool:
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        _app.processEvents()
        if condition():
            return True
        time.sleep(0.01)
    return condition()


class PersonalityTests(unittest.TestCase):
    def test_loads_bundled_file(self):
        personality = Personality.load(PERSONALITY_FILE)
        self.assertEqual(personality.name, "Alter Ego")
        self.assertTrue(personality.greeting)
        self.assertIn("Alter Ego", personality.system_prompt)
        # The list of lines in the JSON is joined into one prompt.
        self.assertGreater(personality.system_prompt.count("\n"), 2)

    def test_missing_file_falls_back_to_default(self):
        personality = Personality.load(Path("does/not/exist.json"))
        self.assertEqual(personality, Personality.default())

    def test_broken_json_falls_back_to_default(self):
        import tempfile

        with tempfile.TemporaryDirectory() as folder:
            broken = Path(folder) / "p.json"
            broken.write_text("{ not json", encoding="utf-8")
            self.assertEqual(Personality.load(broken), Personality.default())


class ConversationTests(unittest.TestCase):
    def test_add_and_clear_emit_signals(self):
        conversation = Conversation()
        added, cleared = [], []
        conversation.message_added.connect(added.append)
        conversation.cleared.connect(lambda: cleared.append(True))

        message = Message(Role.USER, "hello")
        conversation.add(message)
        self.assertEqual(conversation.messages, (message,))
        self.assertEqual(added, [message])

        conversation.clear()
        self.assertEqual(len(conversation), 0)
        self.assertEqual(cleared, [True])


class OfflineResponderTests(unittest.TestCase):
    def setUp(self):
        self.responder = OfflineResponder()
        self.personality = Personality.default()
        self.conversation = Conversation()

    def reply_to(self, text: str) -> Reply:
        return self.responder.reply(text, self.personality, self.conversation)

    def test_every_reply_has_text_and_expression(self):
        for text in ["hi", "how are you?", "who are you", "thanks", "bye", "help",
                     "do you like python?", "what is 2+2?", "just a statement"]:
            reply = self.reply_to(text)
            self.assertTrue(reply.text, text)
            self.assertIsInstance(reply.expression, Expression)

    def test_greeting_is_shy(self):
        self.assertIs(self.reply_to("Hello there").expression, Expression.SHY_TALK)

    def test_tech_topics_are_exciting(self):
        self.assertIn(self.reply_to("tell me about python").expression,
                      (Expression.PASSION_TALK, Expression.SURPRISED_TALK))


class AssistantTests(unittest.TestCase):
    def test_send_records_user_message_then_reply(self):
        conversation = Conversation()
        assistant = Assistant(Personality.default(), conversation)
        states = []
        assistant.state_changed.connect(states.append)

        self.assertTrue(assistant.send("  hello  "))
        self.assertEqual(conversation.messages[0].role, Role.USER)
        self.assertEqual(conversation.messages[0].text, "hello")
        self.assertIs(assistant.state, AssistantState.THINKING)

        # A second message while thinking is refused.
        self.assertFalse(assistant.send("again"))

        self.assertTrue(process_events_until(lambda: len(conversation) == 2))
        reply = conversation.messages[1]
        self.assertEqual(reply.role, Role.ASSISTANT)
        self.assertIsNotNone(reply.expression)
        self.assertEqual(states, [AssistantState.THINKING, AssistantState.IDLE])

    def test_empty_message_is_ignored(self):
        assistant = Assistant(Personality.default(), Conversation())
        self.assertFalse(assistant.send("   "))
        self.assertEqual(len(assistant.conversation), 0)

    def test_greet_only_once(self):
        assistant = Assistant(Personality.default(), Conversation())
        assistant.greet()
        assistant.greet()
        self.assertEqual(len(assistant.conversation), 1)
        self.assertEqual(assistant.conversation.messages[0].text, Personality.default().greeting)


if __name__ == "__main__":
    unittest.main()
