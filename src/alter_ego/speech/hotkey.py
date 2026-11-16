"""The global push-to-talk key.

Alter Ego is usually not the focused window when the user wants to talk, so
the key has to work system-wide. On Windows the key state is polled with
GetAsyncKeyState a few times per tick; that needs no hook or driver and
reports presses and releases, which a registered hotkey would not. Other
platforms get no global key for now (the chat panel's talk button still works).
"""

from __future__ import annotations

import sys

from PySide6.QtCore import QObject, QTimer, Signal

POLL_INTERVAL_MS = 30
DEFAULT_KEY = "F9"

# Key name shown in menus and stored in the config -> Windows virtual-key code.
KEY_CODES: dict[str, int] = {
    **{f"F{n}": 0x6F + n for n in range(1, 13)},
    "Pause": 0x13,
    "Scroll Lock": 0x91,
    "Caps Lock": 0x14,
    "Num Lock": 0x90,
    "Insert": 0x2D,
    "Home": 0x24,
    "End": 0x23,
    "Page Up": 0x21,
    "Page Down": 0x22,
    "Right Ctrl": 0xA3,
    "Right Alt": 0xA5,
    "Right Shift": 0xA1,
    "` (backtick)": 0xC0,
    **{f"Numpad {n}": 0x60 + n for n in range(10)},
    "Numpad +": 0x6B,
    "Numpad -": 0x6D,
    "Numpad *": 0x6A,
    "Numpad /": 0x6F,
    "Numpad .": 0x6E,
    "Mouse 4 (side button)": 0x05,
    "Mouse 5 (side button)": 0x06,
}


def _normalise(name: str) -> str:
    return "".join(ch for ch in name.lower() if ch.isalnum() or ch in "+-*/.`")


_LOOKUP = {_normalise(name): name for name in KEY_CODES}
# Short spellings people are likely to type into the config file.
_LOOKUP.update({
    "rctrl": "Right Ctrl", "rightcontrol": "Right Ctrl",
    "ralt": "Right Alt", "rshift": "Right Shift",
    "scrolllock": "Scroll Lock", "capslock": "Caps Lock", "numlock": "Num Lock",
    "pageup": "Page Up", "pagedown": "Page Down", "pgup": "Page Up", "pgdn": "Page Down",
    "backtick": "` (backtick)", "`": "` (backtick)", "grave": "` (backtick)",
    "mouse4": "Mouse 4 (side button)", "mouse5": "Mouse 5 (side button)",
    "xbutton1": "Mouse 4 (side button)", "xbutton2": "Mouse 5 (side button)",
})


def key_name(name: str) -> str | None:
    """The canonical key name for a config value, or None if it is not a known key."""
    return _LOOKUP.get(_normalise(name)) or (_LOOKUP.get(_normalise(name).split("(")[0]))


class PushToTalkKey(QObject):
    """Emits pressed/released for one global key. start() begins watching, stop() ends it."""

    pressed = Signal()
    released = Signal()

    supported = sys.platform == "win32"

    def __init__(self, name: str = DEFAULT_KEY, parent: QObject | None = None):
        super().__init__(parent)
        self._name = DEFAULT_KEY
        self._code = KEY_CODES[DEFAULT_KEY]
        self._down = False
        self._timer = QTimer(self)
        self._timer.setInterval(POLL_INTERVAL_MS)
        self._timer.timeout.connect(self._poll)
        self.set_key(name)

    @property
    def name(self) -> str:
        return self._name

    @property
    def watching(self) -> bool:
        return self._timer.isActive()

    def set_key(self, name: str) -> None:
        canonical = key_name(name)
        if canonical is None:
            print(f"Warning: unknown push-to-talk key '{name}', using {DEFAULT_KEY}.")
            canonical = DEFAULT_KEY
        self._name = canonical
        self._code = KEY_CODES[canonical]
        if self._down:
            self._down = False
            self.released.emit()

    def start(self) -> None:
        if not self.supported:
            print("Note: the global push-to-talk key only works on Windows; use the talk button in the chat.")
            return
        self._timer.start()

    def stop(self) -> None:
        self._timer.stop()
        if self._down:
            self._down = False
            self.released.emit()

    def _poll(self) -> None:
        down = _key_is_down(self._code)
        if down != self._down:
            self._down = down
            (self.pressed if down else self.released).emit()


def _key_is_down(code: int) -> bool:
    import ctypes

    return bool(ctypes.windll.user32.GetAsyncKeyState(code) & 0x8000)
