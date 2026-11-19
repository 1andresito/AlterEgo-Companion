"""Tests for the chat panel's scrolling while Alter Ego types.

Widgets need a QApplication and other test files already made a QCoreApplication,
so the window runs in a child process (like test_character.py).
"""

from __future__ import annotations

import os
import subprocess
import sys
import textwrap
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]

SCROLL_SCRIPT = textwrap.dedent("""
    import sys
    sys.path.insert(0, sys.argv[1])
    from PySide6.QtWidgets import QApplication
    from alter_ego.chat import ChatWindow
    from alter_ego.core.assistant import Assistant, OfflineResponder
    from alter_ego.core.conversation import Conversation, Message, Role
    from alter_ego.core.personality import Personality

    app = QApplication([])
    conversation = Conversation()
    for i in range(40):
        conversation.add(Message(Role.USER if i % 2 else Role.ASSISTANT, f"Line number {i}, long enough to wrap a bit. " * 3))
    chat = ChatWindow(Assistant(Personality.default(), conversation, OfflineResponder()))
    chat.show()
    app.processEvents()
    bar = chat._view.verticalScrollBar()
    app.processEvents()
    assert bar.maximum() > 0, "the history should be taller than the panel"
    assert bar.value() == bar.maximum(), ("opens at the latest message", bar.value(), bar.maximum())
    chat.hide()
    bar.setValue(0)
    chat.show()
    app.processEvents()
    assert bar.value() == bar.maximum(), ("reopens at the latest message", bar.value(), bar.maximum())
    chat._render()

    # At the bottom: new text keeps the view at the bottom.
    bar.setValue(bar.maximum())
    conversation.add(Message(Role.ASSISTANT, "A new reply that is being typed. " * 4))
    chat._render()
    assert bar.value() == bar.maximum(), (bar.value(), bar.maximum())

    # Scrolled up to read: the view stays where the user put it, while the typing goes on.
    bar.setValue(bar.maximum() // 3)
    kept = bar.value()
    for _ in range(5):
        conversation.update(conversation.messages[-1], text=conversation.messages[-1].text + "more words ")
        chat._render()
    assert bar.value() == kept, (bar.value(), kept)

    # Dragging the scrollbar pauses the typewriter, so nothing moves under the mouse.
    message = conversation.messages[-1]
    chat._typing_message, chat._typed_chars, chat._typed_progress = message, 0, 0.0
    bar.setSliderDown(True)
    chat._type_step()
    assert chat._typed_chars == 0
    bar.setSliderDown(False)
    chat._type_step()
    assert chat._typed_chars > 0
    print("ok")
""")


WAITING_SCRIPT = textwrap.dedent("""
    import sys, time
    sys.path.insert(0, sys.argv[1])
    from PySide6.QtCore import QEvent, Qt
    from PySide6.QtGui import QKeyEvent
    from PySide6.QtWidgets import QApplication
    from alter_ego import chat as chat_module
    from alter_ego.chat import ChatWindow
    from alter_ego.core.assistant import Assistant, AssistantState, OfflineResponder
    from alter_ego.core.conversation import Conversation, Message, Role
    from alter_ego.core.personality import Personality

    app = QApplication([])
    conversation = Conversation()
    assistant = Assistant(Personality.default(), conversation, OfflineResponder())
    chat = ChatWindow(assistant)
    chat.show()
    app.processEvents()
    last_line = lambda: chat._view.toPlainText().strip().splitlines()[-1]

    # Thinking, no words yet: the dots, at once, and they move.
    assistant._set_state(AssistantState.THINKING)
    assert last_line() == "ALTER EGO > thinking.", last_line()
    chat._dots_step()
    assert last_line() == "ALTER EGO > thinking..", last_line()
    assistant._think_deeper()  # a while with nothing new
    assert last_line().startswith("ALTER EGO > thinking some more"), last_line()
    assistant._on_progress("Searching the web...")  # something new: a search
    chat._dots_step()
    assert last_line() == "ALTER EGO > searching the web...", last_line()
    assistant._on_progress("")  # the search is done
    assert last_line().startswith("ALTER EGO > looking at what I found"), last_line()

    # Words arrive and are typed: the dots go. Then they stall mid-reply: the dots come back after the words.
    reply = Message(Role.ASSISTANT, "Let me look.", complete=False)
    conversation.add(reply)
    assistant._set_state(AssistantState.REPLYING)  # as the first words do
    while chat._typed_chars < len(reply.text):
        chat._type_step()
    assert last_line() == "ALTER EGO > Let me look.▌", last_line()
    chat._last_typed_at -= chat_module.STALL_S + 0.5  # well past it: Windows' clock is coarse
    chat._dots_step()
    assert last_line().startswith("ALTER EGO > Let me look. ."), last_line()
    assistant._on_progress("Searching the web...")  # a search mid-reply says so after the words
    assert last_line().startswith("ALTER EGO > Let me look. (searching the web."), last_line()
    assistant._on_progress("")
    conversation.update(reply, text="Let me look. Found it!", complete=True)
    assistant._set_state(AssistantState.IDLE)
    for _ in range(40):
        chat._type_step()
    assert last_line() == "ALTER EGO > Let me look. Found it!", last_line()
    assert not chat._dots_timer.isActive()

    # The input wraps and grows instead of hiding the start; Shift+Enter is a new line, Enter sends.
    box = chat._input
    one_line = box.height()
    box.setText("a long message that keeps going " * 6)
    app.processEvents()
    assert box.height() > one_line, (box.height(), one_line)
    box.setText("first")
    app.sendEvent(box, QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_Return, Qt.KeyboardModifier.ShiftModifier))
    box.insertPlainText("second")
    assert box.text() == "first\\nsecond", repr(box.text())
    app.sendEvent(box, QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_Return, Qt.KeyboardModifier.NoModifier))
    assert conversation.messages[-1].text == "first\\nsecond", conversation.messages[-1].text
    assert box.text() == ""
    assistant.cancel()  # The sent message started a reply on a thread: let it end before quitting.

    # While Alter Ego answers, the button is "stop" and the box can still be typed in; stop frees it at once.
    button = chat._send_button
    for _ in range(50):  # The cancelled reply to the message sent above settles.
        app.processEvents()
        time.sleep(0.01)
    assert button.text() == "send", button.text()
    assistant._set_state(AssistantState.THINKING)
    assert button.text() == "stop" and button.isEnabled() and box.isEnabled()
    box.setText("my next message")
    app.sendEvent(box, QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_Return, Qt.KeyboardModifier.NoModifier))
    assert box.text() == "my next message", "Enter waits while Alter Ego is busy"
    long_reply = Message(Role.ASSISTANT, "A long answer that is still being typed out.", complete=True)
    conversation.add(long_reply)
    assistant._set_state(AssistantState.IDLE)
    assert chat._typing_message is long_reply and button.text() == "stop"
    button.click()
    assert chat._typing_message is None and button.text() == "send"
    assert last_line() == "ALTER EGO > A long answer that is still being typed out.", last_line()

    # The face follows what Alter Ego is thinking about: each new thought, not a clock.
    from pathlib import Path
    from alter_ego.expressions import Expression, ExpressionManager
    from alter_ego import reactions
    faces = ExpressionManager(Path(sys.argv[1]).parent / "assets" / "animations")
    react = reactions.CharacterReactions(faces, assistant, chat)
    seen = []
    faces.expression_changed.connect(lambda new, old: seen.append(new))
    from alter_ego.core import assistant as core
    assistant._depth = 0
    assistant._set_state(AssistantState.THINKING)
    assistant._set_thought(core.THINKING)
    assert faces.current is Expression.SIDE_TALK, faces.current
    assert assistant._deeper_timer.isActive()  # nothing new for a while -> thinking some more
    assistant._think_deeper()
    assert assistant.thought == core.THINKING_MORE and faces.current is Expression.SHY_TALK
    assistant._think_deeper()
    assert assistant.thought == core.THINKING_HARD and faces.current is Expression.SWEAT_TALK
    assert not assistant._deeper_timer.isActive()  # the deepest: it stays, no loop
    assistant._on_progress("Searching the web...")
    assert faces.current is Expression.PASSION_TALK
    assistant._on_progress("")
    assert assistant.thought == core.LOOKING_AT_RESULTS and faces.current is Expression.SURPRISED_TALK
    assistant._on_progress("Reading notes.txt...")
    assert faces.current is Expression.TALK
    assistant._set_state(AssistantState.IDLE)
    assert assistant.thought == "" and not assistant._deeper_timer.isActive()
    assert reactions.face_for("starting Ollama") is Expression.SIDE_TALK
    print("ok")
""")


FIXES_SCRIPT = textwrap.dedent("""
    import sys
    sys.path.insert(0, sys.argv[1])
    from PySide6.QtCore import QObject, Signal
    from PySide6.QtWidgets import QApplication
    from alter_ego import chat as chat_module
    from alter_ego.chat import ChatWindow
    from alter_ego.core.assistant import Assistant, AssistantState, OfflineResponder
    from alter_ego.core.conversation import Conversation, Message, Role
    from alter_ego.core.personality import Personality
    from alter_ego.expressions import Expression

    class FakeSpeaker(QObject):
        sentence_started = Signal(object, int, float)
        finished = Signal(object)
        status = Signal(str)
        failed = Signal(str)
        prepared = Signal(str)
        current_message = None

    app = QApplication([])
    conversation = Conversation()
    assistant = Assistant(Personality.default(), conversation, OfflineResponder())
    speaker = FakeSpeaker()
    chat = ChatWindow(assistant, speaker=speaker)
    chat.show()
    app.processEvents()
    last_line = lambda: chat._view.toPlainText().strip().splitlines()[-1]
    box = chat._input

    # A status wider than the box is shown in full: the empty box grows to fit it.
    one_line = box.height()
    box.setPlaceholderText("Downloading my voice (about 300 MB, only once)...")
    app.processEvents()
    assert box.height() > one_line, (box.height(), one_line)
    assert box.content_height() <= box.viewport().height() + 0.5, (box.content_height(), box.viewport().height())
    box.setPlaceholderText("Say something...")
    app.processEvents()
    assert box.height() == one_line, (box.height(), one_line)

    # Typed lines all fit, and the first one is never scrolled out of view.
    box.setText("a message long enough to wrap onto a few lines in the box")
    app.processEvents()
    assert box.content_height() <= box.viewport().height() + 0.5, (box.content_height(), box.viewport().height())
    assert box.verticalScrollBar().value() == 0
    box.clear()

    # The reply is in, the voice is not playing yet: the wait says so, not "thinking".
    reply = Message(Role.ASSISTANT, "Hello there! Nice to see you.", complete=False)
    speaker.current_message = reply
    assistant._set_state(AssistantState.THINKING)
    conversation.add(reply)
    assistant._set_state(AssistantState.REPLYING)
    conversation.update(reply, complete=True)
    assistant._set_state(AssistantState.IDLE)
    assert last_line().startswith("ALTER EGO > " + chat_module.VOICE_WAIT), last_line()
    speaker.sentence_started.emit(reply, len(reply.text), 0.03)
    for _ in range(20):
        chat._type_step()
    speaker.current_message = None
    speaker.finished.emit(reply)
    for _ in range(5):
        chat._type_step()
    assert last_line() == "ALTER EGO > Hello there! Nice to see you.", last_line()
    assert chat._typing_message is None

    # Something new is asked (by voice) while the last reply is still being typed: all of it shows at once.
    old = Message(Role.ASSISTANT, "An older reply that takes a while to type out.", complete=True)
    conversation.add(old)
    chat._type_step()
    assert chat._typing_message is old
    assistant._set_state(AssistantState.THINKING)
    assert chat._typing_message is None
    assert "An older reply that takes a while to type out." in chat._view.toPlainText()
    assert box.placeholderText().endswith("is thinking..."), box.placeholderText()
    assistant._set_state(AssistantState.IDLE)

    # A line said in between (a voice problem) never cuts a streaming reply short, and the reply
    # carries on from where it was instead of being typed again from the start.
    streaming = Message(Role.ASSISTANT, "Words that are streaming in", complete=False)
    assistant._set_state(AssistantState.REPLYING)
    conversation.add(streaming)
    for _ in range(40):
        chat._type_step()
    chat._say("Oops.", Expression.SWEAT_TALK)
    assert "Words that are streaming in▌" in chat._view.toPlainText(), chat._view.toPlainText()
    for _ in range(10):
        chat._type_step()
    assert chat._typing_message is None
    conversation.update(streaming, text="Words that are streaming in, and more")
    assert chat._typing_message is streaming and chat._typed_chars == len("Words that are streaming in, and more")
    conversation.update(streaming, complete=True)
    assistant._set_state(AssistantState.IDLE)
    for _ in range(5):
        chat._type_step()
    assert chat._typing_message is None
    print("ok")
""")


LOADING_SCRIPT = textwrap.dedent("""
    import sys, time
    sys.path.insert(0, sys.argv[1])
    from PySide6.QtWidgets import QApplication
    from alter_ego.loading_window import LoadingWindow

    app = QApplication([])

    def run_until(condition, timeout_s=5.0):
        deadline = time.monotonic() + timeout_s
        while time.monotonic() < deadline and not condition():
            app.processEvents()
            time.sleep(0.01)
        return condition()

    # Closes once every step is ticked.
    finished = []
    window = LoadingWindow(timeout_s=30)
    window.add_step("brain", "Starting my brain")
    window.add_step("voice", "Loading my voice")
    window.finished.connect(lambda: finished.append("steps"))
    window.start()
    assert window.isVisible()
    window.step_done("brain")
    assert not run_until(lambda: finished, 0.6), "one step is still loading"
    window.step_done("voice")
    assert run_until(lambda: finished == ["steps"])
    assert not window.isVisible()
    window.step_done("voice")  # A late report after closing is harmless.

    # Never waits past its time-out.
    slow = LoadingWindow(timeout_s=0.2)
    slow.add_step("voice", "Loading my voice")
    slow.finished.connect(lambda: finished.append("timeout"))
    slow.start()
    assert run_until(lambda: "timeout" in finished)

    # Nothing to wait for: finishes at once, without showing.
    empty = LoadingWindow()
    empty.finished.connect(lambda: finished.append("empty"))
    empty.start()
    assert run_until(lambda: "empty" in finished) and not empty.isVisible()
    print("ok")
""")


class LoadingWindowTests(unittest.TestCase):
    def test_closes_when_ready_or_after_its_time_out(self):
        env = dict(os.environ, QT_QPA_PLATFORM="offscreen")
        done = subprocess.run([sys.executable, "-c", LOADING_SCRIPT, str(PROJECT_ROOT / "src")],
                              capture_output=True, text=True, env=env, timeout=60)
        self.assertEqual(done.returncode, 0, done.stderr[-2000:])
        self.assertIn("ok", done.stdout)


class ChatWaitingTests(unittest.TestCase):
    def test_dots_while_thinking_and_an_input_that_wraps(self):
        env = dict(os.environ, QT_QPA_PLATFORM="offscreen")
        done = subprocess.run([sys.executable, "-c", WAITING_SCRIPT, str(PROJECT_ROOT / "src")],
                              capture_output=True, text=True, env=env, timeout=60)
        self.assertEqual(done.returncode, 0, done.stderr[-2000:])
        self.assertIn("ok", done.stdout)


class ChatFixesTests(unittest.TestCase):
    def test_statuses_fit_the_box_and_thinking_is_only_shown_while_thinking(self):
        env = dict(os.environ, QT_QPA_PLATFORM="offscreen")
        done = subprocess.run([sys.executable, "-c", FIXES_SCRIPT, str(PROJECT_ROOT / "src")],
                              capture_output=True, text=True, env=env, timeout=60)
        self.assertEqual(done.returncode, 0, done.stderr[-2000:])
        self.assertIn("ok", done.stdout)


class ChatScrollTests(unittest.TestCase):
    def test_reading_back_is_not_interrupted_by_typing(self):
        env = dict(os.environ, QT_QPA_PLATFORM="offscreen")
        done = subprocess.run([sys.executable, "-c", SCROLL_SCRIPT, str(PROJECT_ROOT / "src")],
                              capture_output=True, text=True, env=env, timeout=60)
        self.assertEqual(done.returncode, 0, done.stderr[-2000:])
        self.assertIn("ok", done.stdout)


if __name__ == "__main__":
    unittest.main()
