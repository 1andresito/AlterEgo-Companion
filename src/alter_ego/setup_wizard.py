"""The setup window: Alter Ego asks for what it needs, the first time it starts.

Three pages, in the chat panel's colours:

    CHOOSE --Set up--> WORKING --(runner finished)--> DONE --Let's talk!--> closed
       └──Skip for now────────────────────────────────────────────────────> closed

The page shows only what is missing: installing Ollama, an AI model (the user
picks one, or none), and the voice files. Nothing is ticked that would download
without the user seeing its size first. The work itself is done by
core/first_run.SetupRunner on a worker thread; this module only draws it.
Reopened any time from AI -> Set up Ollama and my voice...
"""

from __future__ import annotations

import sys

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QCloseEvent
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QHBoxLayout,
    QLabel,
    QProgressBar,
    QPushButton,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from .core.first_run import MODEL_CHOICES, STEP_LABELS, SetupChoices, SetupPlan, SetupRunner, SetupStep
from .providers import ollama_install

WIDTH = 500

STYLE = """
QDialog, QWidget#page { background: #0b1f0b; }
QLabel, QCheckBox {
    color: #d5ffbd;
    font-family: Consolas, "Courier New", monospace;
    font-size: 10pt;
}
QLabel#heading { color: #baff85; font-size: 12pt; font-weight: bold; }
QLabel#done { color: #8dff45; }
QLabel#hint { color: #6f9a5a; font-size: 9pt; }
QCheckBox::indicator { width: 14px; height: 14px; border: 1px solid #8dff45; background: #10250d; }
QCheckBox::indicator:checked { background: #8dff45; }
QComboBox {
    background: #10250d; color: #e4ffd6; border: 1px solid #4cff28; border-radius: 4px; padding: 3px 6px;
    font-family: Consolas, "Courier New", monospace; font-size: 10pt;
}
QComboBox:disabled { color: #6f9a5a; border-color: #2f6d12; }
QComboBox QAbstractItemView { background: #10250d; color: #e4ffd6; selection-background-color: #2f6d12; }
QPushButton {
    background: #10250d; border: 1px solid #8dff45; border-radius: 4px; color: #baff85; padding: 5px 14px;
    font-family: Consolas, "Courier New", monospace; font-size: 10pt;
}
QPushButton:hover { background: #1a3a14; }
QPushButton:pressed { background: #2f6d12; }
QPushButton:disabled { color: #6f9a5a; border-color: #2f6d12; }
QProgressBar {
    background: #10250d; border: 1px solid #4cff28; border-radius: 4px; height: 14px; text-align: center;
    color: #e4ffd6; font-family: Consolas, "Courier New", monospace; font-size: 9pt;
}
QProgressBar::chunk { background: #2f6d12; }
"""


def _label(text: str, name: str = "") -> QLabel:
    label = QLabel(text)
    label.setWordWrap(True)
    label.setTextFormat(Qt.TextFormat.PlainText)
    if name:
        label.setObjectName(name)
    return label


class SetupWizard(QDialog):
    # The window was closed: after the setup ran, or skipped. The app then marks setup done and applies settings.
    completed = Signal()

    def __init__(self, plan: SetupPlan, runner: SetupRunner, parent: QWidget | None = None):
        super().__init__(parent)
        self._plan = plan
        self._runner = runner
        self._choices = SetupChoices()
        self.setWindowTitle("Alter Ego - Setup")
        self.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, True)
        self.setFixedWidth(WIDTH)
        self.setStyleSheet(STYLE)

        self._pages = QStackedWidget()
        self._pages.addWidget(self._build_choose_page())
        self._pages.addWidget(self._build_working_page())
        self._pages.addWidget(self._build_done_page())
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self._pages)

        runner.step_started.connect(self._on_step_started)
        runner.progress.connect(self._on_progress)
        runner.step_done.connect(lambda step, text: self._add_result(step, True, text))
        runner.step_failed.connect(lambda step, text: self._add_result(step, False, text))
        runner.finished.connect(self._on_finished)

        if not plan.anything_missing:
            self._show_done(nothing_to_do=True)

    # ----- Page 1: what to get -----

    def _build_choose_page(self) -> QWidget:
        page, layout = self._page()
        plan = self._plan
        layout.addWidget(_label("Hi! I'm Alter Ego.", "heading"))
        layout.addWidget(_label(
            "Before we talk, I need a few things on this computer. Everything runs here, on your own "
            "machine. Nothing is downloaded unless you tick it."
        ))

        self._ollama_box: QCheckBox | None = None
        if plan.uses_ollama:
            if plan.ollama_installed:
                layout.addWidget(_label("[done] Ollama, my AI brain, is installed.", "done"))
            elif plan.can_install_ollama:
                size = f", about {ollama_install.WINDOWS_DOWNLOAD_MB / 1000:.1f} GB" if sys.platform == "win32" else ""
                self._ollama_box = QCheckBox(f"Install Ollama, my AI brain (free{size})")
                self._ollama_box.setChecked(True)
                layout.addWidget(self._ollama_box)
            else:
                layout.addWidget(_label(f"I need Ollama to think. To install it, {ollama_install.manual_hint()}"))

        self._model_combo: QComboBox | None = None
        if plan.uses_ollama:
            if plan.models:
                layout.addWidget(_label(f"[done] I have an AI model: {plan.models[0]}.", "done"))
            else:
                layout.addWidget(_label("Which AI model should I think with?"))
                combo = QComboBox()
                for choice in MODEL_CHOICES:
                    combo.addItem(f"{choice.label} ({choice.size_gb:g} GB)", choice.name)
                combo.addItem("Not now", "")
                self._model_combo = combo
                layout.addWidget(combo)
                if plan.models is None and plan.ollama_installed:
                    layout.addWidget(_label("If you already have it, I won't download it again.", "hint"))
                if self._ollama_box is not None:
                    self._ollama_box.toggled.connect(lambda _on: self._update_model_enabled())
                self._update_model_enabled()

        self._voice_box: QCheckBox | None = None
        if plan.voice_needed:
            self._voice_box = QCheckBox(f"Download my voice, so I can talk out loud ({plan.voice_size_mb} MB)")
            self._voice_box.setChecked(True)
            layout.addWidget(self._voice_box)

        layout.addStretch(1)
        layout.addWidget(_label("You can come back here any time: AI -> Set up Ollama and my voice...", "hint"))
        buttons = QHBoxLayout()
        skip = QPushButton("Skip for now")
        skip.clicked.connect(self.close)
        start = QPushButton("Set up")
        start.setDefault(True)
        start.clicked.connect(self._start)
        buttons.addWidget(skip)
        buttons.addStretch(1)
        buttons.addWidget(start)
        layout.addLayout(buttons)
        return page

    def _update_model_enabled(self) -> None:
        if self._model_combo is None:
            return
        # A model needs Ollama: available when it is installed, or about to be.
        available = self._plan.ollama_installed or (self._ollama_box is not None and self._ollama_box.isChecked())
        self._model_combo.setEnabled(available)

    def choices(self) -> SetupChoices:
        """What is ticked right now."""
        install = self._ollama_box is not None and self._ollama_box.isChecked()
        model = ""
        if self._model_combo is not None and self._model_combo.isEnabled():
            model = str(self._model_combo.currentData() or "")
        voice = self._voice_box is not None and self._voice_box.isChecked()
        return SetupChoices(install_ollama=install, model=model, voice=voice)

    def _start(self) -> None:
        self._choices = self.choices()
        if not self._choices.steps():
            self.close()
            return
        self._pages.setCurrentIndex(1)
        self._runner.start(self._plan, self._choices)

    # ----- Page 2: working -----

    def _build_working_page(self) -> QWidget:
        page, layout = self._page()
        layout.addWidget(_label("Getting ready...", "heading"))
        self._step_label = _label("")
        self._progress_label = _label("", "hint")
        self._bar = QProgressBar()
        self._bar.setRange(0, 0)
        self._results_label = _label("")
        layout.addWidget(self._step_label)
        layout.addWidget(self._bar)
        layout.addWidget(self._progress_label)
        layout.addWidget(self._results_label)
        layout.addStretch(1)
        layout.addWidget(_label("This can take a while on a slow connection. You can keep using your computer.", "hint"))
        return page

    def _on_step_started(self, step: SetupStep) -> None:
        self._step_label.setText(f"{STEP_LABELS[step]}...")
        self._progress_label.setText("")
        self._bar.setRange(0, 0)

    def _on_progress(self, text: str, percent: int) -> None:
        self._progress_label.setText(text)
        if percent >= 0:
            self._bar.setRange(0, 100)
            self._bar.setValue(min(100, percent))
        else:
            self._bar.setRange(0, 0)

    def _add_result(self, step: SetupStep, ok: bool, text: str) -> None:
        line = f"[done] {text}" if ok else f"[failed] {STEP_LABELS[step]}: {text}"
        current = self._results_label.text()
        self._results_label.setText(f"{current}\n{line}" if current else line)

    def _on_finished(self) -> None:
        self._show_done(nothing_to_do=False)

    # ----- Page 3: done -----

    def _build_done_page(self) -> QWidget:
        page, layout = self._page()
        self._done_heading = _label("All set!", "heading")
        self._done_text = _label("")
        layout.addWidget(self._done_heading)
        layout.addWidget(self._done_text)
        layout.addStretch(1)
        buttons = QHBoxLayout()
        buttons.addStretch(1)
        talk = QPushButton("Let's talk!")
        talk.setDefault(True)
        talk.clicked.connect(self.close)
        buttons.addWidget(talk)
        layout.addLayout(buttons)
        return page

    def _show_done(self, nothing_to_do: bool) -> None:
        if nothing_to_do:
            self._done_heading.setText("Everything is ready.")
            self._done_text.setText("I have everything I need. Click me on your desktop to chat.")
        else:
            failed = [step for step, (ok, _text) in self._runner.results.items() if not ok]
            self._done_heading.setText("Almost there..." if failed else "All set!")
            lines = [("[done] " if ok else "[failed] ") + text for _step, (ok, text) in self._runner.results.items()]
            if failed:
                lines.append("")
                lines.append("You can try again any time: AI -> Set up Ollama and my voice...")
            else:
                lines.append("")
                lines.append("Click me on your desktop to chat. Hold F9 to talk to me.")
            self._done_text.setText("\n".join(lines))
        self._pages.setCurrentIndex(2)

    # ----- Window -----

    def _page(self) -> tuple[QWidget, QVBoxLayout]:
        page = QWidget()
        page.setObjectName("page")
        layout = QVBoxLayout(page)
        layout.setContentsMargins(20, 18, 20, 16)
        layout.setSpacing(10)
        return page, layout

    @property
    def page_index(self) -> int:
        return self._pages.currentIndex()

    def closeEvent(self, event: QCloseEvent) -> None:  # noqa: N802 (Qt naming)
        if self._runner.running:
            event.ignore()  # An installer is half-way through; closing now would leave it in an unknown state.
            return
        super().closeEvent(event)
        self.completed.emit()
