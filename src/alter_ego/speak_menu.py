"""The "Spoken replies" submenu: voice on/off, engine, voice, pitch, speed, volume, speakers.

Shared by the character's right-click menu and the tray menu, like the AI,
Voice and Memory menus. Every change is saved at once and applied through
`apply_settings`, which rebuilds the engine and restyles the voice.
"""

from __future__ import annotations

from typing import Callable

from PySide6.QtGui import QActionGroup
from PySide6.QtWidgets import QMenu

from .expressions import Expression
from .settings.config import Config
from .voice import SYNTHESIZER_LABELS, Speaker
from .voice.kokoro_local import ENGLISH_VOICES, MODELS, OTHER_VOICES, VOICES
from .voice.player import DEFAULT_DEVICE, SpeechPlayer

TEST_LINE = "Testing, testing... can you hear me? Um, this is what my voice sounds like. I hope it's okay."

PITCHES = [(-2, "Lower"), (0, "Natural"), (1, "A little higher"), (2, "Higher (default)"), (4, "Highest")]
SPEEDS = [(0.85, "Slower"), (1.0, "Normal"), (1.15, "Faster")]
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

    # --- Engine ---
    radio_menu(
        menu.addMenu("Engine"), "synthesizer", list(SYNTHESIZER_LABELS.items()),
        str(config.get("voice", "synthesizer", "kokoro") or "kokoro"),
    )

    # --- Voice (Kokoro): English voices first, the rest in a submenu ---
    voice_menu = menu.addMenu("Voice")
    current_voice = str(config.get("voice", "kokoro_voice", "alter_ego") or "alter_ego")
    radio_menu(voice_menu, "kokoro_voice", [(name, VOICES[name]) for name in ENGLISH_VOICES], current_voice)
    radio_menu(voice_menu.addMenu("Other languages"), "kokoro_voice", [(name, VOICES[name]) for name in OTHER_VOICES], current_voice)
    radio_menu(
        menu.addMenu("Voice model"), "kokoro_model",
        [(key, f"{key.title()} ({size} MB)") for key, (_file, size) in MODELS.items()],
        str(config.get("voice", "kokoro_model", "standard") or "standard"),
    )

    # --- Delivery ---
    radio_menu(menu.addMenu("Pitch"), "pitch", PITCHES, int(round(number("pitch", 2))))
    radio_menu(menu.addMenu("Speed"), "speed", SPEEDS, round(number("speed", 1.0), 2))
    radio_menu(menu.addMenu("Volume"), "volume", VOLUMES, round(number("volume", 0.8), 2))

    crt = menu.addAction("Computer-voice effect")
    crt.setCheckable(True)
    crt.setChecked(bool(config.get("voice", "crt_effect", True)))
    crt.setToolTip("A light 'speaking from inside a monitor' tone")
    crt.triggered.connect(lambda checked: save("crt_effect", bool(checked)))

    # --- Speakers (listed when the submenu opens, so newly plugged-in devices show up) ---
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
