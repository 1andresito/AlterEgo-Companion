"""The "Voice" submenu: push to talk on/off, the key, the microphone, the recognition engine.

Shared by the character's right-click menu and the tray menu, like the AI and
Memory menus. Every change is saved at once and applied through
`apply_settings`, which rebuilds the recorder, engine and key watcher.
"""

from __future__ import annotations

from typing import Callable

from PySide6.QtGui import QActionGroup
from PySide6.QtWidgets import QMenu

from .core.assistant import Assistant
from .settings.config import Config
from .speech import TRANSCRIBER_LABELS
from .speech.controller import PushToTalk
from .speech.hotkey import DEFAULT_KEY, KEY_CODES, PushToTalkKey, key_name
from .speech.recorder import DEFAULT_DEVICE, MicrophoneRecorder
from .speech.vad import DEFAULT_SENSITIVITY, SENSITIVITY_LEVELS
from .speech.whisper_local import MODELS as WHISPER_MODELS


def add_voice_menu(
    parent: QMenu,
    push_to_talk: PushToTalk,
    assistant: Assistant,
    config: Config,
    apply_settings: Callable[[], None],
) -> QMenu:
    menu = parent.addMenu("Voice")

    def save(section_key: str, value: object) -> None:
        config.set("speech", section_key, value)
        config.save()
        apply_settings()

    def radio_menu(title: str, key: str, choices: list[tuple[str, str]], current: str) -> QMenu:
        """A submenu of mutually exclusive choices: [(value, label), ...]."""
        submenu = menu.addMenu(title)
        group = QActionGroup(submenu)
        for value, label in choices:
            action = submenu.addAction(label)
            action.setCheckable(True)
            action.setChecked(value == current)
            group.addAction(action)
            action.triggered.connect(lambda checked=False, value=value: save(key, value))
        return submenu

    # --- On/off ---
    current_key = key_name(str(config.get("speech", "push_to_talk_key", DEFAULT_KEY) or "")) or DEFAULT_KEY
    where = f"hold {current_key}" if PushToTalkKey.supported else "talk button in the chat"
    enabled = menu.addAction(f"Push to talk ({where})")
    enabled.setCheckable(True)
    enabled.setChecked(config.speech_enabled)
    enabled.triggered.connect(lambda checked: save("enabled", bool(checked)))

    # --- Hands-free: the microphone stays open, so it is opt-in and says so ---
    phrase = str(config.get("speech", "wake_phrase", "hey alter ego") or "hey alter ego").title()
    hands_free = menu.addAction(f'Hands-free (say "{phrase}")')
    hands_free.setCheckable(True)
    hands_free.setChecked(config.hands_free_enabled)
    hands_free.setEnabled(config.speech_enabled)
    hands_free.setToolTip("Keeps the microphone open, listening locally for the wake phrase")
    hands_free.triggered.connect(lambda checked: save("hands_free", bool(checked)))
    radio_menu(
        "Wake sensitivity", "wake_sensitivity",
        [(level, {"low": "Low (loud, close speech only)", "normal": "Normal", "high": "High (quiet or distant speech)"}[level])
         for level in SENSITIVITY_LEVELS],
        str(config.get("speech", "wake_sensitivity", DEFAULT_SENSITIVITY) or DEFAULT_SENSITIVITY),
    )

    # --- Key ---
    radio_menu("Key", "push_to_talk_key", [(name, name) for name in KEY_CODES], current_key)

    # --- Microphone (listed when the submenu opens, so newly plugged-in devices show up) ---
    microphone_menu = menu.addMenu("Microphone")

    def fill_microphones() -> None:
        microphone_menu.clear()
        current = str(config.get("speech", "microphone", DEFAULT_DEVICE) or DEFAULT_DEVICE)
        group = QActionGroup(microphone_menu)
        for value, label in [(DEFAULT_DEVICE, "System default")] + [(d, d) for d in MicrophoneRecorder.available_devices()]:
            action = microphone_menu.addAction(label)
            action.setCheckable(True)
            action.setChecked(value == current)
            group.addAction(action)
            action.triggered.connect(lambda checked=False, value=value: save("microphone", value))

    microphone_menu.aboutToShow.connect(fill_microphones)

    # --- Engine and model ---
    radio_menu(
        "Speech recognition", "transcriber", list(TRANSCRIBER_LABELS.items()),
        str(config.get("speech", "transcriber", "whisper") or "whisper"),
    )
    radio_menu(
        "Whisper model", "whisper_model", [(m, m) for m in WHISPER_MODELS],
        str(config.get("speech", "whisper_model", "base") or "base"),
    )

    # --- Behaviour ---
    review = menu.addAction("Review before sending")
    review.setCheckable(True)
    review.setChecked(bool(config.get("speech", "review_before_sending", False)))
    review.setToolTip("Put the recognised text in the input box instead of sending it at once")
    review.triggered.connect(lambda checked: save("review_before_sending", bool(checked)))

    menu.addSeparator()
    prepare = menu.addAction("Prepare speech recognition")
    prepare.setToolTip("Download/load the speech model now, so the first press is fast")
    prepare.triggered.connect(lambda: push_to_talk.prepare())
    return menu
