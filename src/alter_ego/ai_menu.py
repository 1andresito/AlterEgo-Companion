"""The "AI" submenu: choose a provider and model, test the connection.

Shared by the character's right-click menu and the tray menu. Changes are
saved to the config file immediately and applied through `apply_settings`,
which rebuilds the assistant's responder.
"""

from __future__ import annotations

from typing import Callable

from PySide6.QtCore import QUrl
from PySide6.QtGui import QActionGroup, QDesktopServices
from PySide6.QtWidgets import QMenu

from .core.assistant import Assistant, ProviderResponder
from .core.conversation import Message, Role
from .expressions import Expression
from .providers import OFFLINE_ID, PROVIDER_LABELS, ProviderError
from .settings.config import Config


def add_ai_menu(parent: QMenu, assistant: Assistant, config: Config, apply_settings: Callable[[], None]) -> QMenu:
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

    # --- Test connection: Alter Ego reports the result in the chat ---
    def test_connection() -> None:
        try:
            summary = assistant.responder.test_connection()
            expression = Expression.PASSION_TALK
        except ProviderError as error:
            summary = f"Hmm... {error}"
            expression = Expression.SWEAT_TALK
        assistant.conversation.add(Message(Role.ASSISTANT, summary, expression=expression))

    # --- Settings file: URLs and API keys live there until a settings window exists ---
    def edit_settings_file() -> None:
        if not config.path.exists():
            config.save()  # Write the defaults so the user has something to edit.
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(config.path)))

    menu.addSeparator()
    menu.addAction("Test connection", test_connection)
    menu.addAction("Edit settings file...", edit_settings_file)
    return menu
