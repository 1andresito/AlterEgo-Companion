"""Tests for the Linux uninstaller's questions (packaging/linux/uninstall.sh), on a fake home folder.

The Windows uninstaller (packaging/windows/alter_ego.iss) asks the same in a window; Inno Setup
code is only compiled by the release workflow, so it is checked there and by hand.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = PROJECT_ROOT / "packaging" / "linux" / "uninstall.sh"
SHELL = shutil.which("sh") or shutil.which("bash")


@unittest.skipIf(SHELL is None, "no POSIX shell on this computer")
class LinuxUninstallTests(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.home = Path(folder.name)
        self.paths = {
            "program": self.home / ".local/share/alter-ego/AlterEgo",
            "memory": self.home / ".config/alter_ego/memory.db",
            "settings": self.home / ".config/alter_ego/config.json",
            "voices": self.home / ".config/alter_ego/voices/kokoro.onnx",
            "speech": self.home / ".cache/huggingface/hub/models--Systran--faster-whisper-base/model.bin",
            "other_cache": self.home / ".cache/huggingface/hub/models--someone--else/model.bin",
            "files": self.home / "Documents/Alter Ego/notes.txt",
            "ollama_models": self.home / ".ollama/models/blob",
        }
        for path in self.paths.values():
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("x", encoding="utf-8")

    def uninstall(self, answers: str) -> str:
        env = {k: v for k, v in os.environ.items()
               if k not in ("ALTER_EGO_DATA_DIR", "XDG_DATA_HOME", "XDG_CONFIG_HOME", "HF_HOME", "OLLAMA_MODELS")}
        env.update(HOME=self.home.as_posix(), ALTER_EGO_ASK="1")
        done = subprocess.run([SHELL, SCRIPT.as_posix()], input=answers, capture_output=True, text=True,
                              env=env, timeout=60)
        self.assertEqual(done.returncode, 0, done.stderr)
        return done.stdout

    def kept(self) -> set[str]:
        return {name for name, path in self.paths.items() if path.exists()}

    def test_saying_no_keeps_everything_but_the_program(self):
        self.uninstall("n\n" * 8)
        self.assertEqual(self.kept(), set(self.paths) - {"program"})

    def test_each_choice_removes_only_its_own_part(self):
        # everything? no / memories? yes / voices? no / speech? yes / files? no / ollama models? no
        self.uninstall("n\ny\nn\ny\nn\nn\n")
        self.assertEqual(self.kept(), {"voices", "other_cache", "files", "ollama_models"})

    def test_everything_removes_all_of_it_but_other_programs_caches(self):
        self.uninstall("y\n")
        self.assertEqual(self.kept(), {"other_cache"})  # only Alter Ego's speech models go
        self.assertFalse((self.home / ".config/alter_ego").exists())


if __name__ == "__main__":
    unittest.main()
