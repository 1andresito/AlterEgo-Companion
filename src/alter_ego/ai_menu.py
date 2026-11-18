"""The "AI" submenu: choose a provider and model, what the AI may do, test the connection.

Shared by the character's right-click menu and the tray menu. Changes are
saved to the config file immediately and applied through `apply_settings`,
which rebuilds the assistant's responder.
"""

from __future__ import annotations

from typing import Callable

from PySide6.QtCore import QUrl
from PySide6.QtGui import QActionGroup, QDesktopServices
from PySide6.QtWidgets import QMenu, QMessageBox

from .core.assistant import Assistant, ProviderResponder
from .providers import OFFLINE_ID, PROVIDER_LABELS, ProviderError, tools_folder
from .settings.config import Config
from .tool_approval import on_top_box, show_on_top


def add_ai_menu(parent: QMenu, assistant: Assistant, config: Config, apply_settings: Callable[[], None],
                open_setup: Callable[[], None] | None = None,
                check_updates: Callable[[], None] | None = None) -> QMenu:
    menu = parent.addMenu("AI")

    # --- Provider ---
    provider_menu = menu.addMenu("Provider")
    group = QActionGroup(provider_menu)
    for provider_id, label in PROVIDER_LABELS.items():
        action = provider_menu.addAction(label)
        action.setCheckable(True)
        action.setChecked(provider_id == config.provider)
        group.addAction(action)

        def choose_provider(checked=False, provider_id=provider_id) -> None:
            config.provider = provider_id
            config.save()
            apply_settings()

        action.triggered.connect(choose_provider)

    # --- Model (only meaningful for a real provider) ---
    model_menu = menu.addMenu("Model")

    def fill_model_menu() -> None:
        model_menu.clear()
        responder = assistant.responder
        if not isinstance(responder, ProviderResponder):
            model_menu.addAction("Offline mode has no models").setEnabled(False)
            return
        try:
            models = responder.provider.list_models()
        except ProviderError as error:
            model_menu.addAction(str(error)).setEnabled(False)
            return
        if not models:
            model_menu.addAction("No models installed").setEnabled(False)
            return

        provider_id = responder.provider.id
        current = str(config.get(provider_id, "model", "") or "")
        model_group = QActionGroup(model_menu)
        for name in models:
            action = model_menu.addAction(name)
            action.setCheckable(True)
            action.setChecked(name == current or (not current and name == models[0]))
            model_group.addAction(action)

            def choose_model(checked=False, name=name, provider_id=provider_id) -> None:
                config.set(provider_id, "model", name)
                config.save()

            action.triggered.connect(choose_model)

    model_menu.aboutToShow.connect(fill_model_menu)

    # --- Test connection: runs on a worker thread; Alter Ego reports the result in the chat ---
    def test_connection() -> None:
        assistant.test_connection()

    # --- Settings file: URLs and API keys live there until a settings window exists ---
    def edit_settings_file() -> None:
        if not config.path.exists():
            config.save()  # Write the defaults so the user has something to edit.
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(config.path)))

    # --- What the AI may do besides talking (core/tools.py) ---
    menu.addSeparator()

    def add_toggle(label: str, key: str):
        action = menu.addAction(label)
        action.setCheckable(True)
        action.setChecked(bool(config.get("tools", key, True)))

        def toggled(checked: bool, key=key) -> None:  # key=key freezes the loop value for this action.
            config.set("tools", key, bool(checked))
            config.save()
            apply_settings()

        action.toggled.connect(toggled)
        return action

    add_toggle("Allow internet", "internet")
    files_action = add_toggle("Let me work with files", "files")

    # Changing files without asking: off by default, and turning it on needs a second yes.
    auto_edit = menu.addAction("Edit files without asking (risky)")
    auto_edit.setCheckable(True)
    auto_edit.setChecked(bool(config.get("tools", "auto_edit", False)))
    auto_edit.setEnabled(files_action.isChecked())
    files_action.toggled.connect(auto_edit.setEnabled)

    def toggle_auto_edit(checked: bool) -> None:
        if checked and not confirm_auto_edit():
            auto_edit.blockSignals(True)
            auto_edit.setChecked(False)
            auto_edit.blockSignals(False)
            return
        config.set("tools", "auto_edit", bool(checked))
        config.save()
        apply_settings()

    auto_edit.toggled.connect(toggle_auto_edit)

    def open_files_folder() -> None:
        folder = tools_folder(config)
        folder.mkdir(parents=True, exist_ok=True)
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(folder)))

    menu.addAction("Open my files folder", open_files_folder)

    menu.addSeparator()
    if open_setup is not None:
        menu.addAction("Set up Ollama and my voice...", open_setup)
    menu.addAction("Test connection", test_connection)
    menu.addAction("Edit settings file...", edit_settings_file)

    # --- Updates (update_prompt.py): asked at start-up, never installed without a yes ---
    if check_updates is not None:
        menu.addSeparator()
        auto = menu.addAction("Check for updates at start-up")
        auto.setCheckable(True)
        auto.setChecked(bool(config.get("updates", "check", True)))

        def toggle_auto(checked: bool) -> None:
            config.set("updates", "check", bool(checked))
            config.save()

        auto.toggled.connect(toggle_auto)
        menu.addAction("Check for updates now", check_updates)
    return menu


AUTO_EDIT_WARNING = (
    "Um... are you sure? With this on, I'll create and overwrite files anywhere you can, "
    "without checking with you first.\n\n"
    "If I get something wrong, I could overwrite something important, and that can't be undone. "
    "I'll still ask before touching system folders or my own folders, and before reading "
    "files outside my folder."
)


def confirm_auto_edit() -> bool:
    """The warning before auto-edit is switched on. True only for an explicit "Turn it on"."""
    box = on_top_box(AUTO_EDIT_WARNING, QMessageBox.Icon.Warning)
    turn_on = box.addButton("Turn it on", QMessageBox.ButtonRole.DestructiveRole)
    keep_off = box.addButton("Keep asking me", QMessageBox.ButtonRole.RejectRole)
    box.setDefaultButton(keep_off)
    box.setEscapeButton(keep_off)
    show_on_top(box)
    return box.clickedButton() is turn_on
