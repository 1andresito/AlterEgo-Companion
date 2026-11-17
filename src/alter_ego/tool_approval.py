"""Asking the user before Alter Ego changes their files.

The AI's file tools run on worker threads (the Ollama reply worker, or the
approval server that answers Claude Code's tool server). They call
`ToolApproval.ask(folder)`, which hands the question to the GUI thread through
a queued signal and waits for the answer; only the worker waits, never the
window.

    worker: ask(folder) --asked--> GUI: "I'm going to be editing <folder>. Is this okay?"
                     <--answer---       Yes / No

A "yes" holds for that folder until Alter Ego quits; a "no" is asked again
next time the user wants a file made.
"""

from __future__ import annotations

import threading
from pathlib import Path
from typing import Callable

from PySide6.QtCore import QObject, QThread, Signal
from PySide6.QtWidgets import QMessageBox, QWidget

# An unanswered question counts as "no" after this long, so a reply cannot hang forever.
ANSWER_TIMEOUT_S = 170


class ToolApproval(QObject):
    _asked = Signal(str, object)  # folder, the threading.Event-backed answer box

    def __init__(self, parent_widget: Callable[[], QWidget | None] = lambda: None, parent: QObject | None = None):
        super().__init__(parent)
        self._parent_widget = parent_widget
        self._approved: set[str] = set()
        self._lock = threading.Lock()
        self._asked.connect(self._show_question)

    def ask(self, folder: Path) -> bool:
        """May the AI change files in `folder`? Called from any thread; blocks that thread until answered."""
        key = str(Path(folder))
        with self._lock:
            if key in self._approved:
                return True
        if QThread.currentThread() is self.thread():
            allowed = self._question(key)  # Already on the GUI thread (not the usual path): ask directly.
        else:
            box = {"event": threading.Event(), "allowed": False}
            self._asked.emit(key, box)
            box["event"].wait(ANSWER_TIMEOUT_S)
            allowed = bool(box["allowed"])
        if allowed:
            with self._lock:
                self._approved.add(key)
        return allowed

    # ----- GUI thread -----

    def _show_question(self, folder: str, box: dict) -> None:
        try:
            box["allowed"] = self._question(folder)
        finally:
            box["event"].set()

    def _question(self, folder: str) -> bool:
        answer = QMessageBox.question(
            self._parent_widget(),
            "Alter Ego",
            f"Um... I'm going to be editing your folder\n{folder}\n\nIs this okay?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        return answer == QMessageBox.StandardButton.Yes
