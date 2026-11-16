"""The "Memory" submenu: switch persistent memory on or off, see what is stored, forget everything.

Shared by the character's right-click menu and the tray menu, like the AI menu.
"""

from __future__ import annotations

from typing import Callable

from PySide6.QtWidgets import QMenu, QMessageBox

from .core.assistant import Assistant
from .core.memory import MemoryStore
from .settings.config import Config


def add_memory_menu(
    parent: QMenu,
    store: MemoryStore,
    assistant: Assistant,
    config: Config,
    apply_settings: Callable[[], None],
) -> QMenu:
    menu = parent.addMenu("Memory")

    remember = menu.addAction("Remember conversations")
    remember.setCheckable(True)
    remember.setChecked(config.memory_enabled)
    remember.setToolTip("Save the chat so it continues where it left off after a restart")

    def toggle_remember(checked: bool) -> None:
        config.set("memory", "enabled", bool(checked))
        config.save()
        apply_settings()

    remember.triggered.connect(toggle_remember)

    menu.addSeparator()

    # A disabled line showing how much is stored, refreshed each time the menu opens.
    status = menu.addAction("")
    status.setEnabled(False)

    def refresh_status() -> None:
        conversations, messages = store.stats()
        if messages == 0:
            status.setText("Nothing remembered yet")
        else:
            status.setText(f"{messages} message(s) in {conversations} conversation(s)")

    menu.aboutToShow.connect(refresh_status)
    refresh_status()

    def forget_everything() -> None:
        answer = QMessageBox.question(
            None,
            "Forget everything?",
            "This deletes every saved conversation:\n"
            f"{store.path}\n\n"
            f"{assistant.personality.name} will not remember anything you have talked about. Continue?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        assistant.cancel()
        store.forget_all()
        # Clearing also tells the provider to drop its own session (Claude Code keeps one).
        assistant.conversation.clear()

    menu.addAction("Forget everything...", forget_everything)
    return menu
