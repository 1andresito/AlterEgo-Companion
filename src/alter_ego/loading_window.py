"""The small window shown while Alter Ego wakes up, before the character appears.

    Alter Ego is waking up...
      ✓ Starting my brain
      ... Loading my voice
    [=====      ]

Each step is ticked when its part reports in (app.py connects them: the AI
model's warm-up, the voice loading). When every step is done, or after
TIMEOUT_S whatever happens, the window closes and `finished` fires, and the
character switches on. A step that fails is ticked too: the reason is said in
the chat, as before. Quitting from the tray works while it is open.
"""

from __future__ import annotations

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QApplication, QHBoxLayout, QLabel, QProgressBar, QVBoxLayout, QWidget

TIMEOUT_S = 90       # Never wait longer than this: a slow step goes on in the background.
CLOSE_DELAY_MS = 400  # The last tick stays visible for a moment.
BUSY, DONE = "...", "✓"

STYLE = """
QWidget#loading { background: #071a07; border: 2px solid #3f9e2a; border-radius: 10px; }
QLabel { color: #baff85; font-family: Consolas, "Courier New", monospace; font-size: 10pt; }
QLabel#title { color: #8dff45; font-size: 11pt; font-weight: bold; }
QProgressBar { background: #0d2b0b; border: 1px solid #3f9e2a; border-radius: 4px; height: 8px; }
QProgressBar::chunk { background: #8dff45; }
"""


class LoadingWindow(QWidget):
    finished = Signal()

    def __init__(self, icon: QIcon | None = None, timeout_s: float = TIMEOUT_S, parent: QWidget | None = None):
        super().__init__(parent)
        self.setObjectName("loading")
        self.setWindowTitle("Alter Ego")
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowStaysOnTopHint
                            | Qt.WindowType.Tool)
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setStyleSheet(STYLE)
        if icon is not None:
            self.setWindowIcon(icon)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(22, 18, 22, 18)
        header = QHBoxLayout()
        if icon is not None:
            picture = QLabel()
            picture.setPixmap(icon.pixmap(36, 36))
            header.addWidget(picture)
        title = QLabel("Alter Ego is waking up...")
        title.setObjectName("title")
        header.addWidget(title, 1)
        layout.addLayout(header)
        self._steps_layout = QVBoxLayout()
        layout.addLayout(self._steps_layout)
        bar = QProgressBar()
        bar.setRange(0, 0)  # Busy: the steps don't know how far along they are.
        bar.setTextVisible(False)
        layout.addWidget(bar)
        self.setFixedWidth(340)

        self._steps: dict[str, tuple[QLabel, str]] = {}
        self._done = False
        self._timeout = QTimer(self)
        self._timeout.setSingleShot(True)
        self._timeout.setInterval(int(timeout_s * 1000))
        self._timeout.timeout.connect(self.finish)

    # ----- Steps -----

    def add_step(self, key: str, label: str) -> None:
        widget = QLabel(f"  {BUSY} {label}")
        self._steps_layout.addWidget(widget)
        self._steps[key] = (widget, label)

    def step_done(self, key: str) -> None:
        step = self._steps.get(key)
        if step is None or self._done:
            return
        widget, label = step
        widget.setText(f"  {DONE} {label}")
        self._steps[key] = (widget, DONE)
        if all(state == DONE for _, state in self._steps.values()):
            QTimer.singleShot(CLOSE_DELAY_MS, self.finish)

    @property
    def has_steps(self) -> bool:
        return bool(self._steps)

    # ----- Showing and closing -----

    def start(self) -> None:
        """Show the window in the middle of the screen; with no steps, finish at once."""
        if not self._steps:
            QTimer.singleShot(0, self.finish)
            return
        self.adjustSize()
        screen = QApplication.primaryScreen()
        if screen is not None:
            frame = self.frameGeometry()
            frame.moveCenter(screen.availableGeometry().center())
            self.move(frame.topLeft())
        self.show()
        self.raise_()
        self._timeout.start()

    def finish(self) -> None:
        if self._done:
            return
        self._done = True
        self._timeout.stop()
        self.hide()  # Kept, not deleted: later warm-ups ("Test connection") still report to it, harmlessly.
        self.finished.emit()
