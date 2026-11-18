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
    chat._render()
    assert bar.maximum() > 0, "the history should be taller than the panel"

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


class ChatScrollTests(unittest.TestCase):
    def test_reading_back_is_not_interrupted_by_typing(self):
        env = dict(os.environ, QT_QPA_PLATFORM="offscreen")
        done = subprocess.run([sys.executable, "-c", SCROLL_SCRIPT, str(PROJECT_ROOT / "src")],
                              capture_output=True, text=True, env=env, timeout=60)
        self.assertEqual(done.returncode, 0, done.stderr[-2000:])
        self.assertIn("ok", done.stdout)


if __name__ == "__main__":
    unittest.main()
