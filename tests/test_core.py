"""Tests for the non-visual core: personality, conversation, assistant.

Run from the project root with:  python -m unittest discover -s tests -v
"""

from __future__ import annotations

import sys
import tempfile
import time
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from PySide6.QtCore import QCoreApplication  # noqa: E402

from alter_ego.core.assistant import (  # noqa: E402
    Assistant,
    AssistantState,
    OfflineResponder,
    ProviderResponder,
    clean_reply,
    split_expression_tag,
    with_tag,
)
from alter_ego.core.conversation import Conversation, Message, Role  # noqa: E402
from alter_ego.core.personality import Personality  # noqa: E402
from alter_ego.expressions import Expression  # noqa: E402
from alter_ego.providers.base import ChatMessage, Provider, ProviderError  # noqa: E402
from alter_ego.settings.config import Config  # noqa: E402

PERSONALITY_FILE = PROJECT_ROOT / "assets" / "personality" / "alter_ego.json"

# Signals and threads need an application object; one per test process is enough.
_app = QCoreApplication.instance() or QCoreApplication(sys.argv)


def process_events_until(condition, timeout_s: float = 5.0) -> bool:
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        _app.processEvents()
        if condition():
            return True
        time.sleep(0.01)
    return condition()


def collect(iterator) -> str:
    return "".join(iterator)


class FakeResponder:
    """Streams a fixed reply in small pieces, like a real provider would."""

    def __init__(self, reply: str, piece_size: int = 3, fail_with: str | None = None):
        self.reply = reply
        self.piece_size = piece_size
        self.fail_with = fail_with
        self.calls: list[tuple[str, tuple]] = []

    def describe(self):
        return "fake"

    def test_connection(self):
        return "fake ok"

    def reset(self):
        pass

    def warm_up(self, progress):
        progress("fake warming up")

    def prepare(self, progress):
        progress("fake preparing")
        if self.fail_with and self.fail_with.startswith("prepare:"):
            raise ProviderError(self.fail_with[len("prepare:"):])

    def stream_reply(self, text, personality, history, cancelled):
        self.calls.append((text, tuple(history)))
        if self.fail_with:
            raise ProviderError(self.fail_with)
        for start in range(0, len(self.reply), self.piece_size):
            yield self.reply[start:start + self.piece_size]


class FakeProvider(Provider):
    id = "fake"
    label = "Fake"

    def __init__(self, models=("model-a", "model-b")):
        self.models = list(models)
        self.last_messages: list[ChatMessage] = []
        self.last_model = ""

    def describe(self):
        return "Fake provider"

    def list_models(self):
        return list(self.models)

    def stream_reply(self, messages, model, cancelled):
        self.last_messages = messages
        self.last_model = model
        yield "[happy] "
        yield "hi"


class PersonalityTests(unittest.TestCase):
    def test_loads_bundled_file(self):
        personality = Personality.load(PERSONALITY_FILE)
        self.assertEqual(personality.name, "Alter Ego")
        self.assertTrue(personality.greeting)
        self.assertIn("Alter Ego", personality.system_prompt)
        self.assertGreater(personality.system_prompt.count("\n"), 2)

    def test_missing_file_falls_back_to_default(self):
        self.assertEqual(Personality.load(Path("does/not/exist.json")), Personality.default())

    def test_broken_json_falls_back_to_default(self):
        with tempfile.TemporaryDirectory() as folder:
            broken = Path(folder) / "p.json"
            broken.write_text("{ not json", encoding="utf-8")
            self.assertEqual(Personality.load(broken), Personality.default())


class ConfigTests(unittest.TestCase):
    def test_defaults_then_save_and_reload(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "sub" / "config.json"
            config = Config.load(path)
            self.assertEqual(config.provider, "ollama")
            self.assertEqual(config.get("ollama", "base_url"), "http://localhost:11434")

            config.provider = "offline"
            config.set("ollama", "model", "llama3.2")
            config.set("future", "key", 1)
            config.save()

            reloaded = Config.load(path)
            self.assertEqual(reloaded.provider, "offline")
            self.assertEqual(reloaded.get("ollama", "model"), "llama3.2")
            self.assertEqual(reloaded.get("ollama", "base_url"), "http://localhost:11434")
            self.assertEqual(reloaded.get("future", "key"), 1)

    def test_broken_file_uses_defaults(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "config.json"
            path.write_text("[1, 2]", encoding="utf-8")
            self.assertEqual(Config.load(path).provider, "ollama")


class ConversationTests(unittest.TestCase):
    def test_add_update_clear_emit_signals(self):
        conversation = Conversation()
        added, updated, cleared = [], [], []
        conversation.message_added.connect(added.append)
        conversation.message_updated.connect(updated.append)
        conversation.cleared.connect(lambda: cleared.append(True))

        message = Message(Role.ASSISTANT, "hel", complete=False)
        conversation.add(message)
        self.assertEqual(added, [message])
        self.assertTrue(conversation.contains(message))

        conversation.update(message, text="hello", expression=Expression.TALK, complete=True)
        self.assertEqual(updated, [message])
        self.assertEqual(message.text, "hello")
        self.assertTrue(message.complete)

        conversation.clear()
        self.assertEqual(len(conversation), 0)
        self.assertFalse(conversation.contains(message))
        self.assertEqual(cleared, [True])


class ExpressionTagTests(unittest.TestCase):
    def test_known_tag_is_split(self):
        self.assertEqual(split_expression_tag("[shy] Hello"), (Expression.SHY_TALK, "Hello", True))
        self.assertEqual(split_expression_tag("  [Nervous]Hmm"), (Expression.SWEAT_TALK, "Hmm", True))

    def test_no_tag(self):
        self.assertEqual(split_expression_tag("Hello"), (None, "Hello", True))

    def test_unknown_tag_is_kept(self):
        self.assertEqual(split_expression_tag("[1] first"), (None, "[1] first", True))

    def test_undecided_while_tag_incomplete(self):
        self.assertEqual(split_expression_tag("[sh"), (None, "", False))
        self.assertEqual(split_expression_tag(""), (None, "", False))

    def test_long_bracket_without_close_is_text(self):
        text = "[" + "x" * 40
        self.assertEqual(split_expression_tag(text), (None, text, True))

    def test_with_tag_round_trip(self):
        tagged = with_tag(Expression.PASSION_TALK, "Computers!")
        self.assertEqual(split_expression_tag(tagged), (Expression.PASSION_TALK, "Computers!", True))
        self.assertEqual(with_tag(None, "plain"), "plain")


class CleanReplyTests(unittest.TestCase):
    def test_stage_directions_removed(self):
        self.assertEqual(clean_reply("*giggles* Hi there! *typing noises*", final=True), "Hi there!")
        self.assertEqual(clean_reply("I **really** like it.", final=True), "I really like it.")

    def test_emojis_removed(self):
        self.assertEqual(clean_reply("Hello! \U0001F60A\U0001F4BB How are you? ✨", final=True),
                         "Hello! How are you?")

    def test_unmatched_star_is_held_back_while_streaming(self):
        self.assertEqual(clean_reply("Hi there. *nerv", final=False), "Hi there. ")
        self.assertEqual(clean_reply("Hi there. *nervous laugh* I", final=False), "Hi there. I")

    def test_unmatched_star_is_dropped_when_final(self):
        self.assertEqual(clean_reply("Hi there. *nerv", final=True), "Hi there. nerv")

    def test_plain_text_untouched(self):
        self.assertEqual(clean_reply("Just talking, nothing fancy.", final=True), "Just talking, nothing fancy.")


class OfflineResponderTests(unittest.TestCase):
    def setUp(self):
        self.responder = OfflineResponder()
        self.responder.THINK_DELAY_RANGE_S = (0, 0)

    def reply_to(self, text):
        raw = collect(self.responder.stream_reply(text, Personality.default(), (), lambda: False))
        expression, visible, decided = split_expression_tag(raw)
        self.assertTrue(decided)
        return expression, visible

    def test_every_reply_has_text_and_expression(self):
        for text in ["hi", "how are you?", "who are you", "thanks", "bye", "help",
                     "do you like python?", "what is 2+2?", "just a statement"]:
            expression, visible = self.reply_to(text)
            self.assertTrue(visible, text)
            self.assertIsInstance(expression, Expression, text)

    def test_greeting_is_shy(self):
        self.assertIs(self.reply_to("Hello there")[0], Expression.SHY_TALK)

    def test_tech_topics_are_exciting(self):
        self.assertIn(self.reply_to("tell me about python")[0],
                      (Expression.PASSION_TALK, Expression.SURPRISED_TALK))


class ProviderResponderTests(unittest.TestCase):
    def make(self, model_setting=""):
        config = Config(Path("unused.json"), {"fake": {"model": model_setting}})
        provider = FakeProvider()
        return ProviderResponder(provider, config), provider

    def test_uses_configured_model_or_first_available(self):
        responder, _ = self.make("model-b")
        self.assertEqual(responder.resolve_model(), "model-b")
        responder, _ = self.make("")
        self.assertEqual(responder.resolve_model(), "model-a")

    def test_no_models_is_a_provider_error(self):
        responder, provider = self.make("")
        provider.models = []
        with self.assertRaises(ProviderError):
            responder.resolve_model()

    def test_builds_prompt_from_personality_and_history(self):
        responder, provider = self.make("model-a")
        personality = Personality.default()
        history = (
            Message(Role.ASSISTANT, "Hi there.", expression=Expression.SHY_TALK),
            Message(Role.USER, "hello"),
            Message(Role.ASSISTANT, "partial", complete=False),  # skipped: not finished
            Message(Role.USER, "how are you?"),
        )
        text = collect(responder.stream_reply("how are you?", personality, history, lambda: False))
        self.assertEqual(text, "[happy] hi")
        self.assertEqual(provider.last_model, "model-a")

        roles = [m.role for m in provider.last_messages]
        self.assertEqual(roles, ["system", "assistant", "user", "user"])
        self.assertTrue(provider.last_messages[0].content.startswith(personality.system_prompt))
        self.assertIn("[shy]", provider.last_messages[0].content)   # tag instruction present
        self.assertEqual(provider.last_messages[1].content, "[shy] Hi there.")


class AssistantTests(unittest.TestCase):
    def run_until_idle(self, assistant):
        self.assertTrue(process_events_until(lambda: assistant.state is AssistantState.IDLE))

    def test_streamed_reply_is_tagged_and_updated(self):
        conversation = Conversation()
        responder = FakeResponder("[surprised] Oh! Twelve.", piece_size=4)
        assistant = Assistant(Personality.default(), conversation, responder)
        states, updates = [], []
        assistant.state_changed.connect(states.append)
        conversation.message_updated.connect(lambda m: updates.append(m.text))

        self.assertTrue(assistant.send("  what is 5+7?  "))
        self.assertEqual(conversation.messages[0].text, "what is 5+7?")
        self.assertIs(assistant.state, AssistantState.THINKING)
        self.assertFalse(assistant.send("again"))  # busy

        self.run_until_idle(assistant)
        self.assertEqual(len(conversation), 2)
        reply = conversation.messages[1]
        self.assertEqual(reply.text, "Oh! Twelve.")
        self.assertIs(reply.expression, Expression.SURPRISED_TALK)
        self.assertTrue(reply.complete)
        self.assertEqual(states, [AssistantState.THINKING, AssistantState.REPLYING, AssistantState.IDLE])
        self.assertGreater(len(updates), 1)  # text grew over several updates

        # The responder saw the history including the new user message.
        text, history = responder.calls[0]
        self.assertEqual(text, "what is 5+7?")
        self.assertEqual([m.role for m in history], [Role.USER])

    def test_stage_directions_are_stripped_from_streamed_reply(self):
        conversation = Conversation()
        assistant = Assistant(Personality.default(), conversation,
                              FakeResponder("[shy] *blushes* Th-thank you! \U0001F60A *looks away*", piece_size=2))
        assistant.send("you're great")
        self.run_until_idle(assistant)
        self.assertEqual(conversation.messages[1].text, "Th-thank you!")
        self.assertIs(conversation.messages[1].expression, Expression.SHY_TALK)

    def test_untagged_reply_defaults_to_talk(self):
        conversation = Conversation()
        assistant = Assistant(Personality.default(), conversation, FakeResponder("Plain answer."))
        assistant.send("hi")
        self.run_until_idle(assistant)
        reply = conversation.messages[1]
        self.assertEqual(reply.text, "Plain answer.")
        self.assertIs(reply.expression, Expression.TALK)

    def test_provider_failure_becomes_nervous_message(self):
        conversation = Conversation()
        assistant = Assistant(Personality.default(), conversation,
                              FakeResponder("", fail_with="I can't reach Ollama."))
        assistant.send("hi")
        self.run_until_idle(assistant)
        reply = conversation.messages[1]
        self.assertIn("I can't reach Ollama.", reply.text)
        self.assertIs(reply.expression, Expression.SWEAT_TALK)
        self.assertTrue(reply.complete)

    def test_offline_responder_end_to_end(self):
        conversation = Conversation()
        assistant = Assistant(Personality.default(), conversation)  # default responder = offline
        assistant.responder.THINK_DELAY_RANGE_S = (0, 0)
        assistant.send("hello")
        self.run_until_idle(assistant)
        self.assertIs(conversation.messages[1].expression, Expression.SHY_TALK)

    def test_cancel_finishes_cleanly(self):
        conversation = Conversation()

        class SlowResponder(FakeResponder):
            def stream_reply(self, text, personality, history, cancelled):
                yield "[talk] one "
                for _ in range(200):
                    if cancelled():
                        return
                    time.sleep(0.01)
                    yield "more "

        assistant = Assistant(Personality.default(), conversation, SlowResponder(""))
        assistant.send("go")
        self.assertTrue(process_events_until(lambda: assistant.state is AssistantState.REPLYING))
        assistant.cancel()
        self.run_until_idle(assistant)
        self.assertTrue(conversation.messages[1].complete)

    def test_empty_message_is_ignored(self):
        assistant = Assistant(Personality.default(), Conversation())
        self.assertFalse(assistant.send("   "))
        self.assertEqual(len(assistant.conversation), 0)

    def test_prepare_runs_before_the_reply_and_reports_status(self):
        responder = FakeResponder("[happy] Ready.")
        assistant = Assistant(Personality.load(PERSONALITY_FILE), Conversation(), responder)
        status = []
        assistant.status.connect(status.append)
        assistant.send("hi")
        self.assertTrue(process_events_until(lambda: assistant.state is AssistantState.IDLE))
        self.assertEqual(status[0], "fake preparing")
        self.assertEqual(status[-1], "")
        self.assertEqual(assistant.conversation.messages[-1].text, "Ready.")

    def test_prepare_failure_is_a_nervous_message(self):
        responder = FakeResponder("never", fail_with="prepare:Ollama isn't installed.")
        assistant = Assistant(Personality.load(PERSONALITY_FILE), Conversation(), responder)
        assistant.send("hi")
        self.assertTrue(process_events_until(lambda: assistant.state is AssistantState.IDLE))
        reply = assistant.conversation.messages[-1]
        self.assertIn("Ollama isn't installed.", reply.text)
        self.assertIs(reply.expression, Expression.SWEAT_TALK)
        self.assertEqual(responder.calls, [])

    def test_warm_up_and_test_connection_run_on_a_worker(self):
        responder = FakeResponder("[happy] x")
        assistant = Assistant(Personality.load(PERSONALITY_FILE), Conversation(), responder)
        status = []
        assistant.status.connect(status.append)
        self.assertTrue(assistant.warm_up())
        self.assertFalse(assistant.warm_up())  # already busy
        self.assertTrue(process_events_until(lambda: status and status[-1] == ""))
        self.assertIn("fake warming up", status)
        self.assertEqual(len(assistant.conversation), 0)  # a silent warm-up says nothing

        self.assertTrue(process_events_until(lambda: assistant.test_connection()))
        self.assertTrue(process_events_until(lambda: len(assistant.conversation) == 1))
        self.assertIn("fake ok", assistant.conversation.messages[0].text)
        self.assertIn("fake preparing", status)

        failing = FakeResponder("x", fail_with="prepare:no server")
        assistant.set_responder(failing)
        self.assertTrue(process_events_until(lambda: assistant.test_connection()))
        self.assertTrue(process_events_until(lambda: len(assistant.conversation) == 2))
        self.assertIn("no server", assistant.conversation.messages[1].text)

    def test_greet_only_once(self):
        assistant = Assistant(Personality.default(), Conversation())
        assistant.greet()
        assistant.greet()
        self.assertEqual(len(assistant.conversation), 1)


if __name__ == "__main__":
    unittest.main()
