"""Tests for the character window's TV power animation (switching on at start, off at quit)."""

from __future__ import annotations

import os
import subprocess
import sys
import textwrap
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]

POWER_SCRIPT = textwrap.dedent("""
    import sys, time
    from pathlib import Path
    sys.path.insert(0, sys.argv[1])
    from PySide6.QtWidgets import QApplication
    from alter_ego.character import CharacterWindow
    from alter_ego.expressions import ExpressionManager

    app = QApplication([])
    window = CharacterWindow(ExpressionManager(Path(sys.argv[2])))

    def run_until(condition, timeout_s=5.0):
        deadline = time.monotonic() + timeout_s
        while time.monotonic() < deadline and not condition():
            app.processEvents()
            time.sleep(0.005)
        return condition()

    # Switching on: visible at once, the picture grows from nothing to full.
    window.power_on()
    assert window.isVisible() and window.powering
    seen = []
    window._power_animation.valueChanged.connect(lambda value: seen.append(value))
    assert run_until(lambda: not window.powering)
    assert window._power == 1.0 and seen and min(seen) < 0.5, seen
    for level in (0.9, 0.6, 0.3, 0.1):  # Every stage paints without errors.
        window._power = level
        window.grab()
    window._power = 1.0

    # Switching off: hide/show requests are ignored meanwhile, then the window hides and `done` runs once.
    done = []
    window.power_off(lambda: done.append(True))
    window.power_off(lambda: done.append("twice"))
    window.disappear()
    assert run_until(lambda: done)
    assert done == [True] and not window.isVisible(), done

    # Already hidden: quit at once.
    hidden = []
    window.power_off(lambda: hidden.append(True))
    assert hidden == [True]
    print("ok")
""")


class PowerAnimationTests(unittest.TestCase):
    def test_switching_on_and_off(self):
        # A separate process, because the other tests already made a non-GUI application object here.
        env = dict(os.environ, QT_QPA_PLATFORM="offscreen")
        result = subprocess.run(
            [sys.executable, "-c", POWER_SCRIPT, str(PROJECT_ROOT / "src"), str(PROJECT_ROOT / "assets" / "animations")],
            capture_output=True, text=True, timeout=60, env=env,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("ok", result.stdout)


if __name__ == "__main__":
    unittest.main()
