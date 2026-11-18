"""Asking the user before Alter Ego changes their files, or reads outside its folder.

The AI's file tools run on worker threads (the Ollama reply worker, or the
approval server that answers Claude Code's tool server). They call
`ToolApproval.ask(access)`, which hands the question to the GUI thread through
a queued signal and waits for the answer; only the worker waits, never the
window.

    worker: ask(access) --asked--> GUI: "Um... can I change <path>?"
                       <--answer---       Yes / No

Every change is asked about, each time; what is remembered (a "no" for a short
while, a folder the user let me read) lives in the ToolBox (core/tools.py).

The question has no parent window and stays on top: the character and the chat
are frameless stay-on-top tool windows, and a normal dialog could open
underneath them, where it cannot be clicked.
"""

from __future__ import annotations

import threading
from typing import Callable

from PySide6.QtCore import QObject, Qt, QThread, Signal
from PySide6.QtWidgets import QApplication, QMessageBox, QWidget

from .core.tools import CREATE, MAKE_FOLDER, READ, REPLACE, Access

# An unanswered question counts as "no" after this long, so a reply cannot hang forever.
ANSWER_TIMEOUT_S = 170


def question_text(access: Access) -> str:
    """What Alter Ego asks, in its own voice."""
    path = str(access.path)
    if access.kind == CREATE:
        return f"Um... can I make a new file here?\n\n{path}"
    if access.kind == REPLACE:
        return f"Um... can I change this file?\n\n{path}\n\nWhat's in it now will be replaced."
    if access.kind == MAKE_FOLDER:
        return f"Um... can I make a new folder here?\n\n{path}"
    if access.kind == READ:
        return (f"Um... can I look at the files in this folder?\n\n{path}\n\n"
                "What I read goes to the AI you chose.")
    return f"Um... can I use this?\n\n{path}"


def on_top_box(text: str, icon: QMessageBox.Icon = QMessageBox.Icon.Question) -> QMessageBox:
    """A message box that comes up above Alter Ego's stay-on-top windows.
    Add the buttons, then pass it to `show_on_top`."""
    box = QMessageBox()  # No parent: a hidden or tool-window parent can keep it out of sight.
    box.setWindowTitle("Alter Ego")
    box.setIcon(icon)
    box.setText(text)
    box.setWindowModality(Qt.WindowModality.ApplicationModal)
    box.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, True)  # After the modality, which resets the flags.
    return box


def show_on_top(box: QMessageBox, anchor: QWidget | None = None) -> None:
    """Show `box` centred on the screen `anchor` is on, raised and focused, and wait for an answer."""
    screen = anchor.screen() if anchor is not None and anchor.isVisible() else None
    screen = screen or QApplication.primaryScreen()
    box.adjustSize()
    if screen is not None:
        frame = box.frameGeometry()
        frame.moveCenter(screen.availableGeometry().center())
        box.move(frame.topLeft())
    box.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, True)  # Again: some setters reset the window flags.
    box.show()
    box.raise_()
    box.activateWindow()
    QApplication.alert(box)  # Flashes the taskbar if Windows keeps the focus elsewhere.
    box.exec()


class ToolApproval(QObject):
    _asked = Signal(object, object)  # the Access, the threading.Event-backed answer box

    def __init__(self, anchor: Callable[[], QWidget | None] = lambda: None, parent: QObject | None = None):
        super().__init__(parent)
        self._anchor = anchor  # Which screen the question appears on.
        self._asked.connect(self._show_question)

    def ask(self, access: Access) -> bool:
        """May the AI do this? Called from any thread; blocks that thread until answered."""
        if QThread.currentThread() is self.thread():
            return self._question(access)  # Already on the GUI thread (not the usual path): ask directly.
        box = {"event": threading.Event(), "allowed": False}
        self._asked.emit(access, box)
        box["event"].wait(ANSWER_TIMEOUT_S)
        return bool(box["allowed"])

    # ----- GUI thread -----

    def _show_question(self, access: Access, box: dict) -> None:
        try:
            box["allowed"] = self._question(access)
        finally:
            box["event"].set()

    def _make_box(self, access: Access) -> QMessageBox:
        box = on_top_box(question_text(access))
        box.setStandardButtons(QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        box.setDefaultButton(QMessageBox.StandardButton.No)
        if access.detail:
            box.setDetailedText(access.detail)  # The new content, behind "Show Details...".
        return box

    def _question(self, access: Access) -> bool:
        box = self._make_box(access)
        show_on_top(box, self._anchor())
        return box.clickedButton() is box.button(QMessageBox.StandardButton.Yes)
