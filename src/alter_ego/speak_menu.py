"""The "Spoken replies" submenu: voice on/off, volume and speakers.

Shared by the character's right-click menu and the tray menu, like the AI,
Voice and Memory menus. Alter Ego has a single voice, so nothing here picks
a voice, engine, pitch or speed; the menu only says which voice is in use.
Every change is saved at once and applied through
`apply_settings`.
"""

from __future__ import annotations

from typing import Callable

from PySide6.QtGui import QActionGroup
from PySide6.QtWidgets import QMenu

from .expressions import Expression
from .settings.config import Config
from .voice import Speaker, character_model
from .voice.player import DEFAULT_DEVICE, SpeechPlayer

TEST_LINE = "Testing, testing... can you hear me? Um, this is what my voice sounds like. I hope it's okay."

VOLUMES = [(0.25, "25%"), (0.5, "50%"), (0.8, "80%"), (1.0, "100%")]


def add_speak_menu(
    parent: QMenu,
    speaker: Speaker,
    config: Config,
    apply_settings: Callable[[], None],
) -> QMenu:
    menu = parent.addMenu("Spoken replies")

    def save(key: str, value: object) -> None:
        config.set("voice", key, value)
        config.save()
        apply_settings()

    def number(key: str, default: float) -> float:
        try:
            return float(config.get("voice", key, default))
        except (TypeError, ValueError):
            return default

    def radio_menu(submenu: QMenu, key: str, choices: list[tuple[object, str]], current: object) -> None:
        """Fill a submenu with mutually exclusive choices: [(value, label), ...]."""
        group = QActionGroup(submenu)
        for value, label in choices:
            action = submenu.addAction(label)
            action.setCheckable(True)
            action.setChecked(value == current)
            group.addAction(action)
            action.triggered.connect(lambda checked=False, value=value: save(key, value))

    # --- On/off ---
    enabled = menu.addAction("Speak replies out loud")
    enabled.setCheckable(True)
    enabled.setChecked(config.voice_enabled)
    enabled.triggered.connect(lambda checked: save("enabled", bool(checked)))

    # --- The one voice: shown, not chosen ---
    model = character_model()
    shown = menu.addAction("My voice: Alter Ego" if model is not None else "My voice: stand-in (voice file missing)")
    shown.setEnabled(False)

    # --- Loudness and output ---
    radio_menu(menu.addMenu("Volume"), "volume", VOLUMES, round(number("volume", 0.8), 2))

    # Speakers are listed when the submenu opens, so newly plugged-in devices show up.
    speaker_menu = menu.addMenu("Speakers")

    def fill_speakers() -> None:
        speaker_menu.clear()
        current = str(config.get("voice", "speaker", DEFAULT_DEVICE) or DEFAULT_DEVICE)
        radio_menu(
            speaker_menu, "speaker",
            [(DEFAULT_DEVICE, "System default")] + [(d, d) for d in SpeechPlayer.available_devices()],
            current,
        )

    speaker_menu.aboutToShow.connect(fill_speakers)

    menu.addSeparator()
    synthesizer = speaker.synthesizer
    needs_download = synthesizer is not None and synthesizer.needs_download
    size = getattr(synthesizer, "download_size_mb", 0) if needs_download else 0
    prepare = menu.addAction(f"Download my voice ({size} MB)" if needs_download else "Prepare my voice")
    prepare.setToolTip("Download/load the voice now, so the first reply is not delayed")
    prepare.triggered.connect(lambda: speaker.prepare())

    test = menu.addAction("Test my voice")
    test.triggered.connect(lambda: speaker.say(TEST_LINE, Expression.SHY_TALK))
    return menu
