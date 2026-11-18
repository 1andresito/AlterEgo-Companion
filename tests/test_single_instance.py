"""Tests for running only one Alter Ego at a time (single_instance.py) and the per-computer checks."""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import time
import unittest
import uuid
from pathlib import Path
from unittest import mock

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from PySide6.QtCore import QCoreApplication  # noqa: E402

from alter_ego.core import machine  # noqa: E402
from alter_ego.single_instance import NAME_ENV, SingleInstance, instance_name  # noqa: E402

_app = QCoreApplication.instance() or QCoreApplication(sys.argv)


def process_events_until(condition, timeout_s: float = 5.0) -> bool:
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        QCoreApplication.processEvents()
        if condition():
            return True
        time.sleep(0.01)
    return condition()


class SingleInstanceTests(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.folder = Path(folder.name)
        patcher = mock.patch.dict(os.environ, {NAME_ENV: f"AlterEgoTest-{uuid.uuid4().hex[:8]}"})
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_a_second_copy_steps_aside_and_brings_the_first_forward(self):
        first = SingleInstance(self.folder)
        self.assertTrue(first.acquire())
        self.addCleanup(first.release)
        shown = []
        first.show_requested.connect(lambda: shown.append(True))

        # The second copy is another process, as when Alter Ego is started twice.
        script = (
            "import sys; from pathlib import Path; sys.path.insert(0, sys.argv[1])\n"
            "from PySide6.QtCore import QCoreApplication\n"
            "from alter_ego.single_instance import SingleInstance\n"
            "app = QCoreApplication([])\n"
            "second = SingleInstance(Path(sys.argv[2]))\n"
            "print(second.acquire(), second.ask_running_copy_to_show())\n"
        )
        second = subprocess.Popen([sys.executable, "-c", script, str(PROJECT_ROOT / "src"), str(self.folder)],
                                  stdout=subprocess.PIPE, text=True)
        self.assertTrue(process_events_until(lambda: second.poll() is not None, 30))
        self.assertEqual(second.stdout.read().split(), ["False", "True"])  # no lock, but the first answered
        self.assertTrue(process_events_until(lambda: shown))

    def test_after_the_first_copy_quits_a_new_one_may_start(self):
        first = SingleInstance(self.folder)
        self.assertTrue(first.acquire())
        first.release()
        again = SingleInstance(self.folder)
        self.assertTrue(again.acquire())
        again.release()

    def test_each_data_folder_has_its_own_name(self):
        with mock.patch.dict(os.environ, {NAME_ENV: ""}):
            self.assertNotEqual(instance_name(self.folder / "a"), instance_name(self.folder / "b"))
            self.assertEqual(instance_name(self.folder / "a"), instance_name(self.folder / "a"))

    def test_helper_processes_never_take_the_lock(self):
        main = (PROJECT_ROOT / "main.py").read_text(encoding="utf-8")
        run_at = main.index("from alter_ego.app import run")
        for flag in ("--tool-server", "--voice-server", "--check-voice"):
            self.assertLess(main.index(f'"{flag}" in sys.argv'), run_at, flag)


class MachineTests(unittest.TestCase):
    def test_memory_is_read(self):
        self.assertGreater(machine.total_ram_gb(), 0.5)
        self.assertGreater(machine.process_memory_mb(), 0)

    def test_keeping_the_voice_loaded_follows_the_memory_and_can_be_forced(self):
        with mock.patch.dict(os.environ, {machine.KEEP_VOICE_ENV: ""}):
            with mock.patch.object(machine, "total_ram_gb", return_value=8.0):
                self.assertFalse(machine.keep_voice_loaded())
            with mock.patch.object(machine, "total_ram_gb", return_value=32.0):
                self.assertTrue(machine.keep_voice_loaded())
        with mock.patch.dict(os.environ, {machine.KEEP_VOICE_ENV: "0"}):
            self.assertFalse(machine.keep_voice_loaded())
        with mock.patch.dict(os.environ, {machine.KEEP_VOICE_ENV: "1"}):
            self.assertTrue(machine.keep_voice_loaded())

    def test_nvidia_check_never_raises(self):
        self.assertIsInstance(machine.has_nvidia_driver(), bool)


if __name__ == "__main__":
    unittest.main()
