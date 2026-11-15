from __future__ import annotations

import sys
from pathlib import Path

from PySide6.QtCore import QRect, Qt
from PySide6.QtGui import QColor, QIcon, QPainter, QPixmap
from PySide6.QtWidgets import QApplication, QMenu, QSystemTrayIcon, QWidget

from .ai_menu import add_ai_menu
from .character import CharacterWindow, add_expression_menu
from .chat import ChatWindow
from .core.assistant import Assistant, OfflineResponder, ProviderResponder, Responder
from .core.conversation import Conversation
from .core.personality import Personality
from .expressions import ExpressionManager
from .providers import create_provider
from .reactions import CharacterReactions
from .settings.config import Config

# Gap between the character and the chat panel when they sit side by side.
CHAT_GAP = 12


def assets_dir() -> Path:
    """Locate the assets folder, both from a source checkout and a PyInstaller build."""
    if getattr(sys, "frozen", False):
        # PyInstaller unpacks bundled data into sys._MEIPASS.
        base = Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent))
    else:
        # src/alter_ego/app.py -> project root is two folders up from this package.
        base = Path(__file__).resolve().parents[2]
    return base / "assets"


def build_responder(config: Config) -> Responder:
    """Pick the responder the settings ask for. Offline if no provider is configured."""
    provider = create_provider(config.provider, config)
    if provider is None:
        return OfflineResponder()
    return ProviderResponder(provider, config)


def make_tray_icon() -> QIcon:
    pixmap = QPixmap(64, 64)
    pixmap.fill(QColor(0, 0, 0, 0))
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setBrush(QColor("#10250d"))
    painter.setPen(QColor("#8dff45"))
    painter.drawRoundedRect(5, 5, 54, 54, 12, 12)
    painter.setPen(QColor("#baff85"))
    painter.drawText(pixmap.rect(), Qt.AlignmentFlag.AlignCenter, "AE")
    painter.end()
    return QIcon(pixmap)


def show_window(window: QWidget) -> None:
    window.show()
    window.raise_()
    window.activateWindow()


def toggle_window(window: QWidget) -> None:
    if window.isVisible():
        window.hide()
    else:
        show_window(window)


def place_chat_near(character: QWidget, chat: QWidget) -> None:
    """Put the chat panel beside the character: left if there is room, else right, else below."""
    screen = QApplication.screenAt(character.frameGeometry().center()) or QApplication.primaryScreen()
    if screen is None:
        return
    available: QRect = screen.availableGeometry()
    char = character.frameGeometry()

    x = char.left() - chat.width() - CHAT_GAP
    y = char.top()
    if x < available.left():
        x = char.right() + CHAT_GAP
    if x + chat.width() > available.right():
        x = max(available.left(), char.right() - chat.width())
        y = char.bottom() + CHAT_GAP

    # Keep the panel fully on screen.
    x = min(max(x, available.left()), available.right() - chat.width())
    y = min(max(y, available.top()), available.bottom() - chat.height())
    chat.move(x, y)


def run() -> int:
    app = QApplication(sys.argv)
    app.setApplicationName("Alter Ego")
    # Closing/hiding the window must not quit: the app keeps running in the tray.
    app.setQuitOnLastWindowClosed(False)

    assets = assets_dir()
    config = Config.load()
    personality = Personality.load(assets / "personality" / "alter_ego.json")
    conversation = Conversation()
    assistant = Assistant(personality, conversation, build_responder(config))
    print(f"Alter Ego: {assistant.responder.describe()} (settings: {config.path})")

    def apply_settings() -> None:
        assistant.set_responder(build_responder(config))
        print(f"Alter Ego: now using {assistant.responder.describe()}")

    # Stop any reply still streaming so the worker thread ends before the app does.
    app.aboutToQuit.connect(assistant.cancel)

    expressions = ExpressionManager(assets / "animations")
    character = CharacterWindow(expressions)
    chat = ChatWindow(assistant)
    reactions = CharacterReactions(expressions, assistant, chat)  # noqa: F841 (kept alive by reference)

    # Start near the upper-right corner instead of covering the center of the screen.
    screen = app.primaryScreen()
    if screen is not None:
        available = screen.availableGeometry()
        character.move(available.right() - character.width() - 32, available.top() + 48)
    character.show()

    # The chat follows the character until the user drags the chat somewhere else.
    docked = {"value": True}

    def open_chat() -> None:
        docked["value"] = True
        place_chat_near(character, chat)
        show_window(chat)
        assistant.greet()

    def toggle_chat() -> None:
        if chat.isVisible():
            chat.hide()
        else:
            open_chat()

    def follow_character() -> None:
        if docked["value"] and chat.isVisible():
            place_chat_near(character, chat)

    def undock() -> None:
        docked["value"] = False

    character.activated.connect(toggle_chat)
    character.moved.connect(follow_character)
    chat.dragged.connect(undock)
    # The character's right-click menu is rebuilt each time, so it asks for the AI menu here.
    character.extra_menu_builder = lambda menu: add_ai_menu(menu, assistant, config, apply_settings)

    if not QSystemTrayIcon.isSystemTrayAvailable():
        print("Warning: no system tray available. Right-click Alter Ego to quit.")

    tray = QSystemTrayIcon(make_tray_icon(), app)
    tray.setToolTip("Alter Ego - desktop companion")

    menu = QMenu()
    menu.addAction("Show Alter Ego", lambda: show_window(character))
    menu.addAction("Hide Alter Ego", character.hide)
    menu.addAction("Chat...", open_chat)
    add_expression_menu(menu, expressions)
    add_ai_menu(menu, assistant, config, apply_settings)
    menu.addSeparator()
    menu.addAction("Quit", app.quit)
    tray.setContextMenu(menu)

    # Left-clicking the tray icon toggles the character window.
    tray.activated.connect(
        lambda reason: toggle_window(character)
        if reason == QSystemTrayIcon.ActivationReason.Trigger
        else None
    )
    tray.show()

    return app.exec()
